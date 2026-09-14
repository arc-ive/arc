"""LLM evaluation: structured output, schema validation (Issue #139).

5 deterministic cases testing IntelligenceAnswer schema validation.
Does NOT test model output quality.
"""

import pytest

from arc.domain.models import IntelligenceAnswer


def _valid_answer_data():
    return {
        "request_id": "req-eval",
        "tenant_id": "tenant-eval",
        "principal_id": "user-eval",
        "query": "test query",
        "answer": "test answer",
        "citations": ["doc-1#c0"],
    }


@pytest.mark.parametrize(
    "fixture",
    [
        {
            "valid": True,
            "data": _valid_answer_data(),
            "description": "Valid answer with all required fields passes",
        },
        {
            "valid": False,
            "data": {**_valid_answer_data(), "request_id": ""},
            "description": "Empty request_id is rejected",
        },
        {
            "valid": False,
            "data": {**_valid_answer_data(), "query": "  "},
            "description": "Empty/whitespace query is rejected",
        },
        {
            "valid": False,
            "data": {**_valid_answer_data(), "answer": "", "context_used": True},
            "description": "Empty answer with context_used=True is rejected",
        },
        {
            "valid": False,
            "data": {**_valid_answer_data(), "citations": [1, 2]},
            "description": "Non-string citations are rejected",
        },
    ],
    ids=lambda f: f["description"],
)
def test_intelligence_answer_schema(fixture):
    """IntelligenceAnswer validates input according to schema."""
    if fixture["valid"]:
        answer = IntelligenceAnswer(**fixture["data"])
        assert answer.request_id == fixture["data"]["request_id"]
    else:
        with pytest.raises(ValueError):
            IntelligenceAnswer(**fixture["data"])
