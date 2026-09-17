"""Shared fixtures and configuration for the AI evaluation suite.

Issue #139: evaluation/regression test suite per V2-ADR-023.

Two execution modes:
- Deterministic (default): CI-safe, no API key, application-level behavior.
- Production-LLM: requires OPENROUTER_API_KEY, uses free-tier model only.

Agent evaluation is deferred — Agent execution loop is not implemented.
"""

import os

import pytest

EVAL_FREE_MODEL = "openrouter/free"


def pytest_collection_modifyitems(config, items):
    """Skip production-LLM evaluation tests when OPENROUTER_API_KEY is absent."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        skip_marker = pytest.mark.skip(reason="OPENROUTER_API_KEY not set")
        for item in items:
            if "evaluation_real_llm" in item.keywords:
                item.add_marker(skip_marker)
