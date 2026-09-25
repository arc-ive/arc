#!/usr/bin/env python
"""Measure the relevance-floor thresholds for a deployment's real corpus.

A correct ``MIN_RELEVANCE_SCORE`` is not a constant anyone can ship. It is a
property of two things a deployment chooses: the embedding provider (cosine
distributions differ enormously between the deterministic word-hash provider
and a real semantic model) and the tenant's own corpus. A number measured on
someone else's corpus is a guess wearing a safeguard's clothes.

This script derives the thresholds from the corpus that is actually indexed,
through the production retrieval path, and prints the evidence alongside the
recommendation so the number can be audited rather than trusted.

Usage::

    # Against the configured DATABASE_URL and EMBEDDING_PROVIDER
    python scripts/measure_relevance_floor.py \\
        --tenant-id acme \\
        --on-corpus-file on.txt \\
        --off-corpus-file off.txt

``on.txt`` holds queries the corpus SHOULD answer, one per line; ``off.txt``
holds queries it should NOT. Both are deployment-specific: the off-corpus set
should contain realistic near-misses (a policy the company does not have),
not only nonsense, because nonsense is easy to reject and proves little.

Exit codes:
    0  the distributions separate; a threshold is reported
    1  the distributions overlap; no single threshold satisfies both goals
    2  usage / configuration error

An overlap result is a real finding, not a failure of the script: it means
this provider cannot separate these queries on this corpus, and a floor would
have to reject real questions to reject fake ones. Reported honestly rather
than papered over with a midpoint that silences one side.
"""

import argparse
import asyncio
import os
import statistics
import sys
from typing import List, Tuple

from arc.db.connection import ArcDatabase
from arc.domain.models import TenantContext, UserRole
from arc.repositories.retrieval import PostgreSQLKnowledgeChunkRepository
from arc.services.embeddings import build_embedding_provider, get_embedding_settings
from arc.services.retrieval import RetrievalService


def _read_queries(path: str) -> List[str]:
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.startswith("#")]


async def _top_scores(service, context, query) -> Tuple[float, float]:
    """Return (top dense cosine, top lexical ts_rank) for one query."""
    dense = await service.search(context, query)
    lexical = await service.lexical_search(context, query)
    top_dense = dense[0].similarity if dense else 0.0
    top_lexical = lexical[0].lexical_score if lexical and lexical[0].lexical_score else 0.0
    return top_dense, top_lexical


def _report(label: str, scored: List[Tuple[str, float]]) -> None:
    print(f"\n{label}")
    for query, score in sorted(scored, key=lambda pair: -pair[1]):
        print(f"  {score:.6f}  {query}")
    values = [score for _, score in scored]
    if values:
        print(
            f"  -- min={min(values):.6f} max={max(values):.6f} mean={statistics.fmean(values):.6f}"
        )


def _recommend(kind: str, off: List[float], on: List[float], env_var: str) -> bool:
    """Print the recommendation for one score family. True when separated."""
    print(f"\n=== {kind} ===")
    if not off or not on:
        print("  insufficient data (one of the query sets produced no scores)")
        return False
    off_max, on_min = max(off), min(on)
    print(f"  off-corpus max : {off_max:.6f}")
    print(f"  on-corpus  min : {on_min:.6f}")
    if off_max >= on_min:
        print(
            f"  OVERLAP: no {env_var} separates these sets. Any threshold that "
            f"rejects the worst off-corpus query also rejects a real one.\n"
            f"  Do NOT set {env_var} from this run. Either improve the corpus, "
            f"change embedding provider, or leave the floor disabled and rely "
            f"on the generation-side refusal."
        )
        return False
    midpoint = (off_max + on_min) / 2
    print(f"  gap            : {on_min - off_max:.6f}")
    print(f"  RECOMMENDED    : {env_var}={midpoint:.4f}  (midpoint of the measured gap)")
    print(
        f"  Margin to nearest real query: {on_min - midpoint:.6f}. A narrow margin "
        f"means the threshold is fragile to corpus growth — re-measure after "
        f"significant ingestion."
    )
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--on-corpus-file", required=True)
    parser.add_argument("--off-corpus-file", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL must be set", file=sys.stderr)
        return 2

    on_queries = _read_queries(args.on_corpus_file)
    off_queries = _read_queries(args.off_corpus_file)
    if not on_queries or not off_queries:
        print("both query files must be non-empty", file=sys.stderr)
        return 2

    settings = get_embedding_settings()
    print(f"embedding provider : {settings.provider}")
    print(f"embedding model    : {settings.model}")
    print(f"dimensions         : {settings.dimensions}")
    print(f"tenant             : {args.tenant_id}")

    database = ArcDatabase(database_url)
    await database.connect()
    try:
        service = RetrievalService(
            PostgreSQLKnowledgeChunkRepository(database),
            embedding_provider=build_embedding_provider(settings),
        )
        context = TenantContext(
            tenant_id=args.tenant_id,
            tenant_name=args.tenant_id,
            user_id="relevance-floor-measurement",
            role=UserRole.MEMBER,
        )

        on_scored = [(q, await _top_scores(service, context, q)) for q in on_queries]
        off_scored = [(q, await _top_scores(service, context, q)) for q in off_queries]
    finally:
        await database.disconnect()

    _report("ON-CORPUS dense cosine", [(q, s[0]) for q, s in on_scored])
    _report("OFF-CORPUS dense cosine", [(q, s[0]) for q, s in off_scored])
    _report("ON-CORPUS lexical ts_rank", [(q, s[1]) for q, s in on_scored])
    _report("OFF-CORPUS lexical ts_rank", [(q, s[1]) for q, s in off_scored])

    dense_ok = _recommend(
        "DENSE (cosine)",
        [s[0] for _, s in off_scored],
        [s[0] for _, s in on_scored],
        "MIN_RELEVANCE_SCORE",
    )
    # Lexical scores of 0.0 mean "no lexical hit at all", which is already a
    # rejection; they are excluded so they cannot drag the off-corpus maximum
    # down and manufacture a separation that does not exist.
    lexical_ok = _recommend(
        "LEXICAL (ts_rank)",
        [s[1] for _, s in off_scored if s[1] > 0.0],
        [s[1] for _, s in on_scored if s[1] > 0.0],
        "MIN_LEXICAL_RELEVANCE_SCORE",
    )

    print(
        "\nBoth floors must be set for the gate to hold: a dense floor alone is "
        "bypassed by any lexical-only hit, which is what made an off-corpus "
        "query with incidental word overlap still return context."
    )
    return 0 if (dense_ok and lexical_ok) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
