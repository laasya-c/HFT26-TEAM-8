"""Standard API Response Envelopes.

Per WILDSCOPE Solution Guide (p. 18, 20):
- Single object: { "data": {...}, "meta": { "dataset_revision": 1 } }
- List response: { "data": [...], "meta": { "dataset_revision": 1, "total": 42, "limit": 20, "offset": 0 } }
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResponseMeta(BaseModel):
    """Metadata envelope for responses."""
    dataset_revision: int = Field(default=1, description="Current monotonic dataset revision")
    total: Optional[int] = Field(None, description="Total items matching filter (for lists)")
    limit: Optional[int] = Field(None, description="Requested page limit (for lists)")
    offset: Optional[int] = Field(None, description="Requested page offset (for lists)")


class StandardResponse(BaseModel):
    """Generic single resource response wrapper."""
    data: Any
    meta: ResponseMeta


def success_response(data: Any, dataset_revision: int = 1) -> Dict[str, Any]:
    """Helper to format a single object response envelope."""
    return {
        "data": data,
        "meta": {
            "dataset_revision": dataset_revision
        }
    }


def paginated_response(
    items: List[Any],
    total: int,
    limit: int,
    offset: int,
    dataset_revision: int = 1
) -> Dict[str, Any]:
    """Helper to format a list response envelope with pagination."""
    return {
        "data": items,
        "meta": {
            "dataset_revision": dataset_revision,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    }
