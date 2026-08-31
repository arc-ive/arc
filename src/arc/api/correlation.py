"""Observability-owned HTTP correlation context.

The correlation/request ID minted here is the canonical END-TO-END HTTP
correlation identifier (approved decision). It is deliberately distinct
from future Agent *execution* IDs and from domain-contract fields such as
``IntelligenceAnswer.request_id``, which remain owned by Unified
Intelligence and are NOT modified by Observability.
"""

from contextvars import ContextVar
from typing import Optional

# Request-scoped correlation ID; consumed by the logging filter so every
# log line emitted while a request is being served carries it.
request_id_var: ContextVar[Optional[str]] = ContextVar("arc_request_id", default=None)
