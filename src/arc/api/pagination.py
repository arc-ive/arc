"""Shared pagination utilities for Arc list endpoints.

V2-ADR-022: Production list APIs use offset/page pagination.
V2-TRD §25: Response contract — items, page, page_size, total.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

# Defaults and limits — keep conservative; tighten later if needed.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class PaginationParams:
    """Validated limit/offset from query parameters."""

    limit: int
    offset: int

    @classmethod
    def from_query(
        cls,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> "PaginationParams":
        """Parse and validate limit/offset from query parameters.

        Non-positive or missing values fall back to defaults.
        Values above MAX_PAGE_SIZE are clamped.
        """
        if limit is None or limit <= 0:
            resolved_limit = DEFAULT_PAGE_SIZE
        else:
            resolved_limit = min(limit, MAX_PAGE_SIZE)

        if offset is None or offset < 0:
            resolved_offset = 0
        else:
            resolved_offset = offset

        return cls(limit=resolved_limit, offset=resolved_offset)


def paginate(
    items: Sequence[Any],
    total: int,
    params: PaginationParams,
) -> Dict[str, Any]:
    """Wrap a result list in the V2 paginated response contract.

    ``items`` should already be sliced to the current page.
    ``total`` is the full unfiltered count (before limit/offset).
    """
    return {
        "items": list(items),
        "total": total,
        "page": (params.offset // params.limit) + 1,
        "page_size": params.limit,
    }
