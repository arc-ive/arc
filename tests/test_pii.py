"""Tests for the PII Guard service.

Unit tests use fake analyzer/anonymizer engines so they never load the
spaCy model. Integration tests exercise the real Presidio engines and
require the en_core_web_lg model installed in the environment (the
Docker image installs it as part of the project dependencies).
"""

from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import pytest
from presidio_analyzer import RecognizerResult
from presidio_anonymizer import AnonymizerEngine

from arc.services.pii import (
    DEFAULT_ENABLED_CATEGORIES,
    PiiDetection,
    PiiGuardConfig,
    PiiGuardError,
    PiiGuardService,
)

SAMPLE_TEXT = "Contact alice.smith@example.com or John at 212-555-0147."
SAMPLE_SECRET = "alice.smith@example.com"

EMAIL_DETECTION = ("EMAIL_ADDRESS", 8, 31, 0.9)


def require_model() -> None:
    """Fail explicitly when the en_core_web_lg model is unavailable.

    en_core_web_lg is a declared project dependency (pyproject.toml), so a
    missing model is an environment defect, not a reason to silently skip
    the real-Presidio integration tests.
    """
    try:
        import en_core_web_lg  # noqa: F401
    except ImportError as exc:
        raise AssertionError(
            "The en_core_web_lg spaCy model is required by the Presidio "
            "integration tests and is a declared project dependency "
            "(pyproject.toml, en-core-web-lg). Install the project "
            "dependencies (e.g. `pip install -e .`) and re-run; the "
            "integration tests do not silently skip."
        ) from exc


class FakeAnalyzer:
    """Fake Presidio AnalyzerEngine returning configured results."""

    def __init__(self, results: List[Tuple[str, int, int, float]]):
        self.results = results
        self.entities_arg: Optional[List[str]] = None
        self.calls = 0

    def analyze(self, text: str, language: str, entities: Optional[List[str]]):
        self.calls += 1
        self.entities_arg = entities
        return [
            RecognizerResult(entity_type, start, end, score)
            for entity_type, start, end, score in self.results
        ]


class FakeAnonymizer:
    """Fake Presidio AnonymizerEngine applying replace semantics."""

    def __init__(self, text_out: Optional[str] = None):
        self.text_out = text_out
        self.operators_arg: Optional[Dict[str, object]] = None

    def anonymize(self, text: str, analyzer_results, operators: Optional[Dict[str, object]]):
        self.operators_arg = operators
        if self.text_out is not None:
            return SimpleNamespace(text=self.text_out)
        out = text
        for result in sorted(analyzer_results, key=lambda r: -r.start):
            out = out[: result.start] + f"<{result.entity_type}>" + out[result.end :]
        return SimpleNamespace(text=out)


def make_service(
    analyzer_results: List[Tuple[str, int, int, float]],
    config: Optional[PiiGuardConfig] = None,
) -> Tuple[PiiGuardService, FakeAnalyzer, FakeAnonymizer]:
    analyzer = FakeAnalyzer(analyzer_results)
    anonymizer = FakeAnonymizer()
    service = PiiGuardService(
        config=config or PiiGuardConfig(),
        analyzer_engine=analyzer,
        anonymizer_engine=anonymizer,
    )
    return service, analyzer, anonymizer


def test_default_replace_operator_anonymizes_detected_entity() -> None:
    service, analyzer, anonymizer = make_service([EMAIL_DETECTION])

    result = service.sanitize(SAMPLE_TEXT)

    assert result.detected_count == 1
    assert result.sanitized_text == SAMPLE_TEXT.replace(
        "alice.smith@example.com", "<EMAIL_ADDRESS>"
    )
    assert "alice.smith@example.com" not in result.sanitized_text
    assert anonymizer.operators_arg is None
    assert set(analyzer.entities_arg) == set(DEFAULT_ENABLED_CATEGORIES)


def test_detection_metadata_is_reported() -> None:
    service, _, _ = make_service([EMAIL_DETECTION])

    result = service.sanitize(SAMPLE_TEXT)

    detection = result.detections[0]
    assert isinstance(detection, PiiDetection)
    assert detection.entity_type == "EMAIL_ADDRESS"
    assert detection.start == 8
    assert detection.end == 31
    assert detection.score == 0.9


def test_custom_mask_operator_applies_configured_char() -> None:
    config = PiiGuardConfig(operators={"EMAIL_ADDRESS": "mask"}, mask_char="#")
    service, _, anonymizer = make_service([EMAIL_DETECTION], config=config)

    result = service.sanitize(SAMPLE_TEXT)

    assert "alice.smith@example.com" not in result.sanitized_text
    mask_config = anonymizer.operators_arg["EMAIL_ADDRESS"]
    assert mask_config.operator_name == "mask"
    assert mask_config.params["masking_char"] == "#"
    assert mask_config.params["chars_to_mask"] == 23
    assert mask_config.params["from_end"] is False


def test_custom_redact_operator_removes_value() -> None:
    config = PiiGuardConfig(operators={"EMAIL_ADDRESS": "redact"})
    service, _, anonymizer = make_service([EMAIL_DETECTION], config=config)

    result = service.sanitize(SAMPLE_TEXT)

    assert "alice.smith@example.com" not in result.sanitized_text
    assert anonymizer.operators_arg["EMAIL_ADDRESS"].operator_name == "redact"


def test_disabled_category_is_not_detected() -> None:
    config = PiiGuardConfig(enabled_categories={"EMAIL_ADDRESS"})
    service, analyzer, _ = make_service([EMAIL_DETECTION], config=config)

    result = service.sanitize(SAMPLE_TEXT)

    assert analyzer.entities_arg == ["EMAIL_ADDRESS"]
    assert result.detected_count == 1
    assert result.sanitized_text == SAMPLE_TEXT.replace(
        "alice.smith@example.com", "<EMAIL_ADDRESS>"
    )
    assert "212-555-0147" in result.sanitized_text


def test_empty_enabled_categories_returns_unchanged_text() -> None:
    config = PiiGuardConfig(enabled_categories=set())
    service, analyzer, _ = make_service([EMAIL_DETECTION], config=config)

    result = service.sanitize(SAMPLE_TEXT)

    assert result.unchanged is True
    assert result.detected_count == 0
    assert result.sanitized_text == SAMPLE_TEXT
    assert analyzer.calls == 0


def test_non_sensitive_content_is_preserved() -> None:
    text = "The quarterly report is ready for review."
    service, _, _ = make_service([])

    result = service.sanitize(text)

    assert result.unchanged is True
    assert result.detected_count == 0
    assert result.sanitized_text == text


def test_empty_input_returns_empty_result() -> None:
    service, analyzer, _ = make_service([])

    result = service.sanitize("")

    assert result.sanitized_text == ""
    assert result.unchanged is True
    assert result.detected_count == 0
    assert analyzer.calls == 0


def test_non_string_input_raises_type_error() -> None:
    service, _, _ = make_service([])

    with pytest.raises(TypeError):
        service.sanitize(None)  # type: ignore[arg-type]


def test_invalid_operator_config_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported anonymization operators"):
        PiiGuardConfig(operators={"EMAIL_ADDRESS": "obfuscate"})


def test_invalid_mask_char_raises_value_error() -> None:
    with pytest.raises(ValueError, match="mask_char must be a single character"):
        PiiGuardConfig(mask_char="**")


def test_default_categories_are_globally_applicable() -> None:
    assert DEFAULT_ENABLED_CATEGORIES == {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "IBAN_CODE",
        "IP_ADDRESS",
        "US_SSN",
    }


def test_regional_identifiers_remain_configurable() -> None:
    config = PiiGuardConfig(enabled_categories={"US_SSN"})
    service, analyzer, _ = make_service([("US_SSN", 0, 11, 0.9)], config=config)

    result = service.sanitize("111-22-3333")

    assert analyzer.entities_arg == ["US_SSN"]
    assert "111-22-3333" not in result.sanitized_text
    assert "<US_SSN>" in result.sanitized_text


def make_real_anonymizer_service(
    analyzer_results: List[Tuple[str, int, int, float]],
    config: PiiGuardConfig,
) -> PiiGuardService:
    analyzer = FakeAnalyzer(analyzer_results)
    return PiiGuardService(
        config=config,
        analyzer_engine=analyzer,
        anonymizer_engine=AnonymizerEngine(),
    )


def test_mask_covers_entity_longer_than_64_chars() -> None:
    long_value = "a" * 70 + "@example.com"
    assert len(long_value) > 64
    text = f"Contact {long_value} now."
    start = text.index(long_value)
    service = make_real_anonymizer_service(
        [("EMAIL_ADDRESS", start, start + len(long_value), 0.9)],
        PiiGuardConfig(operators={"EMAIL_ADDRESS": "mask"}),
    )

    result = service.sanitize(text)

    assert long_value not in result.sanitized_text
    assert result.sanitized_text[start : start + len(long_value)] == "*" * len(long_value)


def test_mask_covers_multiple_entities_of_different_lengths() -> None:
    long_value = "a" * 70 + "@example.com"
    short_value = "bob@example.com"
    text = f"Contact {long_value} or {short_value}."
    long_start = text.index(long_value)
    short_start = text.index(short_value)
    service = make_real_anonymizer_service(
        [
            ("EMAIL_ADDRESS", long_start, long_start + len(long_value), 0.9),
            ("EMAIL_ADDRESS", short_start, short_start + len(short_value), 0.9),
        ],
        PiiGuardConfig(operators={"EMAIL_ADDRESS": "mask"}),
    )

    result = service.sanitize(text)

    assert long_value not in result.sanitized_text
    assert short_value not in result.sanitized_text
    assert result.sanitized_text[long_start : long_start + len(long_value)] == "*" * len(long_value)
    assert result.sanitized_text[short_start : short_start + len(short_value)] == "*" * len(
        short_value
    )


def test_mask_covers_space_separated_entities_of_same_type() -> None:
    text = "Contact alice@example.com bob@example.com now."
    first_start = text.index("alice@example.com")
    second_start = text.index("bob@example.com")
    service = make_real_anonymizer_service(
        [
            ("EMAIL_ADDRESS", first_start, first_start + len("alice@example.com"), 0.9),
            ("EMAIL_ADDRESS", second_start, second_start + len("bob@example.com"), 0.9),
        ],
        PiiGuardConfig(operators={"EMAIL_ADDRESS": "mask"}),
    )

    result = service.sanitize(text)

    assert "alice@example.com" not in result.sanitized_text
    assert "bob@example.com" not in result.sanitized_text
    merged_span_start = first_start
    merged_span_end = second_start + len("bob@example.com")
    assert result.sanitized_text[merged_span_start:merged_span_end] == "*" * (
        merged_span_end - merged_span_start
    )


def test_analyzer_failure_raises_sanitized_error() -> None:
    class ExplodingAnalyzer:
        def analyze(self, text: str, language: str, entities=None):
            raise RuntimeError(f"boom {text}")

    service = PiiGuardService(
        config=PiiGuardConfig(),
        analyzer_engine=ExplodingAnalyzer(),
        anonymizer_engine=FakeAnonymizer(),
    )

    with pytest.raises(PiiGuardError) as excinfo:
        service.sanitize(SAMPLE_TEXT)

    assert SAMPLE_SECRET not in str(excinfo.value)


def test_anonymizer_failure_raises_sanitized_error() -> None:
    class ExplodingAnonymizer:
        def anonymize(self, text: str, analyzer_results, operators=None):
            raise RuntimeError(f"boom {text}")

    service, _, _ = make_service([EMAIL_DETECTION])
    service._anonymizer_engine = ExplodingAnonymizer()

    with pytest.raises(PiiGuardError) as excinfo:
        service.sanitize(SAMPLE_TEXT)

    assert SAMPLE_SECRET not in str(excinfo.value)


def test_errors_and_logs_never_contain_input_text(caplog: pytest.LogCaptureFixture) -> None:
    class ExplodingAnalyzer:
        def analyze(self, text: str, language: str, entities=None):
            raise RuntimeError(f"boom {text}")

    service = PiiGuardService(
        config=PiiGuardConfig(),
        analyzer_engine=ExplodingAnalyzer(),
        anonymizer_engine=FakeAnonymizer(),
    )
    with caplog.at_level("DEBUG"):
        with pytest.raises(PiiGuardError):
            service.sanitize(SAMPLE_TEXT)

    for record in caplog.records:
        assert SAMPLE_SECRET not in record.getMessage()


class TestPiiIntegration:
    """Real Presidio engines; requires the en_core_web_lg model."""

    @pytest.fixture(scope="class")
    def service(self):
        require_model()
        return PiiGuardService()

    def test_real_email_detection_and_redaction(self, service) -> None:
        text = "Contact alice.smith@example.com for access."

        result = service.sanitize(text)

        assert result.detected_count >= 1
        assert "EMAIL_ADDRESS" in {d.entity_type for d in result.detections}
        assert "alice.smith@example.com" not in result.sanitized_text
        assert "<EMAIL_ADDRESS>" in result.sanitized_text

    def test_real_phone_detection_and_redaction(self, service) -> None:
        text = "Call the support line at 212-555-0147."

        result = service.sanitize(text)

        assert result.detected_count >= 1
        assert "PHONE_NUMBER" in {d.entity_type for d in result.detections}
        assert "212-555-0147" not in result.sanitized_text

    def test_real_person_detection_and_redaction(self, service) -> None:
        text = "John Smith approved the quarterly budget."

        result = service.sanitize(text)

        assert result.detected_count >= 1
        assert "PERSON" in {d.entity_type for d in result.detections}
        assert "John Smith" not in result.sanitized_text

    def test_real_us_ssn_detection_and_redaction(self, service) -> None:
        text = "The employee record shows SSN 111-22-3333 on file."
        config = PiiGuardConfig(enabled_categories={"US_SSN"})

        result = PiiGuardService(config=config).sanitize(text)

        assert result.detected_count >= 1
        assert "US_SSN" in {d.entity_type for d in result.detections}
        assert "111-22-3333" not in result.sanitized_text

    def test_us_ssn_sanitized_by_default(self) -> None:
        """Regression: SSN must be sanitized with default config (V2-ADR-025)."""
        service = PiiGuardService()
        text = "SSN: 111-22-3333, Email: test@example.com"

        result = service.sanitize(text)

        assert result.detected_count >= 2
        assert "111-22-3333" not in result.sanitized_text
        assert "test@example.com" not in result.sanitized_text

    def test_real_credit_card_detection_and_redaction(self, service) -> None:
        text = "Charge the card 4111 1111 1111 1111 to the account."

        result = service.sanitize(text)

        assert result.detected_count >= 1
        assert "CREDIT_CARD" in {d.entity_type for d in result.detections}
        assert "4111 1111 1111 1111" not in result.sanitized_text

    def test_real_non_sensitive_content_is_preserved(self, service) -> None:
        text = "The quarterly report is ready for review."

        result = service.sanitize(text)

        assert result.unchanged is True
        assert result.sanitized_text == text

    def test_real_disabled_category_remains_unchanged(self, service) -> None:
        text = "Contact alice.smith@example.com or call 212-555-0147."
        config = PiiGuardConfig(enabled_categories={"EMAIL_ADDRESS"})

        result = PiiGuardService(config=config).sanitize(text)

        assert "alice.smith@example.com" not in result.sanitized_text
        assert "212-555-0147" in result.sanitized_text

    def test_real_custom_mask_operator(self, service) -> None:
        text = "Contact alice.smith@example.com for access."
        config = PiiGuardConfig(operators={"EMAIL_ADDRESS": "mask"}, mask_char="#")

        result = PiiGuardService(config=config).sanitize(text)

        assert "alice.smith@example.com" not in result.sanitized_text
        assert "#" in result.sanitized_text
