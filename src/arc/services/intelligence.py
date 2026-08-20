"""Unified Intelligence service for Arc (Secure Knowledge Reasoning).

Unified Intelligence is the single intelligence layer (ADR-001): Company
Brain provides retrieval, the Agent capability reasons over the approved
context. This foundation slice implements the first leg of the approved
workflow (PRD 12, PRD 26, TRD 8/10/12/39):

    Authenticated request
        ↓
    Trusted TenantContext (X-10) + permission (knowledge:read)
        ↓
    Approved Context Contract (RetrievalService.approved_search)
        ↓
    LLM provider (reasoning over approved context only)
        ↓
    IntelligenceAnswer (answer + citations)

Security invariants:

- The ONLY retrieval path is ``RetrievalService.approved_search``, which
  returns an ``ApprovedContext`` derived from the trusted tenant context.
  This service holds no repository reference and can never read raw
  documents, vectors, or authorization state.
- The LLM receives ONLY sanitized content and citation references from
  the approved context. The LLM is NOT the authorization system
  (TRD 10.3): authorization is enforced before the LLM is ever reached.
- Fail closed: an embedding or LLM failure propagates (no partial or
  invented answer); when there is no approved context the LLM is never
  invoked and the answer is ``None``.
- No Skill selection, AI Tools, agent workflows, tool calling, webhooks,
  or autonomous actions in this slice: those are later Unified
  Intelligence maturity layers behind the same security boundary.
"""

import uuid
from typing import List, Optional

from arc.domain.models import ApprovedContext, IntelligenceAnswer, TenantContext
from arc.services.llm import DeterministicLlmProvider, LlmProvider
from arc.services.retrieval import RetrievalService


class UnifiedIntelligenceService:
    """Domain service for tenant-scoped knowledge reasoning."""

    def __init__(
        self,
        retrieval: RetrievalService,
        llm_provider: Optional[LlmProvider] = None,
    ):
        self.retrieval = retrieval
        self.llm_provider = llm_provider if llm_provider is not None else DeterministicLlmProvider()

    async def answer_query(
        self, context: TenantContext, query: str, limit: int = 5
    ) -> IntelligenceAnswer:
        """Retrieve approved context and reason over it.

        The tenant boundary comes exclusively from the trusted context;
        retrieval goes through ``approved_search`` only. When no approved
        context matches, the LLM is never invoked and the answer is
        ``None`` (no invented context, no fallback that weakens
        authorization).

        Raises:
            ValueError: for an empty query or a non-positive limit.
            EmbeddingError: when the embedding provider fails; no answer
                is produced (fail closed).
            LlmError: when the LLM provider fails; no partial answer is
                produced (fail closed).
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        if limit < 1:
            raise ValueError("Search limit must be a positive integer")

        approved = await self.retrieval.approved_search(context, query, limit=limit)

        citations = [item.citation_reference for item in approved.items]
        if not approved.items:
            return IntelligenceAnswer(
                request_id=str(uuid.uuid4()),
                tenant_id=context.tenant_id,
                principal_id=context.user_id,
                query=query,
                answer=None,
                citations=[],
                retrieval_method=approved.retrieval_method,
                context_used=False,
            )

        prompt = self._build_prompt(approved, query)
        answer = self.llm_provider.complete(prompt)

        return IntelligenceAnswer(
            request_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            principal_id=context.user_id,
            query=query,
            answer=answer,
            citations=citations,
            retrieval_method=approved.retrieval_method,
            context_used=True,
        )

    @staticmethod
    def _build_prompt(approved: ApprovedContext, query: str) -> str:
        """Assemble the LLM prompt from the approved context ONLY.

        Only sanitized content and citation references cross into the
        prompt. No tenant identifiers, principal identifiers, vectors,
        scores, repository details, or authorization state are included:
        the LLM must reason over the approved knowledge itself.
        """
        lines: List[str] = [
            "You are Arc's Unified Intelligence. Answer using ONLY the "
            "approved context below. Cite sources with their citation "
            "references.",
            "APPROVED CONTEXT:",
        ]
        for index, item in enumerate(approved.items, start=1):
            lines.append(f"[{index}] citation: {item.citation_reference}")
            lines.append(item.content)
        lines.append(f"QUERY: {query}")
        return "\n".join(lines)
