"""PII Guard service for Arc.

An in-process text sanitization service built on Microsoft Presidio
(Analyzer + Anonymizer). It detects configured PII categories in input
text and applies configured anonymization operations so that PII is
removed before text reaches downstream AI processing (PRD 10, TRD 15).

Per TRD 15.5, Presidio is not a complete security boundary: tenant
isolation, access control, data minimization, and secure logging remain
application responsibilities. This service performs no authorization
checks and is not an authorization mechanism.

Behavior notes (implementation decisions, not product requirements):

- The service is stateless: no persistence, no caches, no logs of input
  or detected values.
- Sanitization fails closed: any analysis or anonymization error raises
  PiiGuardError instead of returning unsanitized text.
- Error messages never contain the input text or detected values.
- The default category set and operator behavior are explicit and
  testable via PiiGuardConfig.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

SUPPORTED_OPERATORS = frozenset({"replace", "mask", "redact"})

DEFAULT_ENABLED_CATEGORIES = frozenset(
    {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "US_PASSPORT",
        "US_DRIVER_LICENSE",
        "US_ITIN",
        "IBAN_CODE",
        "IP_ADDRESS",
    }
)

MASK_MAX_CHARS = 64


class PiiGuardError(Exception):
    """Raised when PII analysis or anonymization fails.

    Messages never contain the input text or detected values, so the
    error can be logged safely (TRD 28).
    """


@dataclass
class PiiDetection:
    """A single detected PII entity in the input text."""

    entity_type: str
    start: int
    end: int
    score: float


@dataclass
class PiiResult:
    """Result of a PII sanitization operation."""

    sanitized_text: str
    detections: List[PiiDetection] = field(default_factory=list)

    @property
    def detected_count(self) -> int:
        """Number of PII entities detected in the input."""
        return len(self.detections)

    @property
    def unchanged(self) -> bool:
        """True when no PII was detected and the text was left as is."""
        return not self.detections


@dataclass
class PiiGuardConfig:
    """Configuration for the PII Guard service.

    Defaults are implementation decisions, not PRD/TRD/ADR requirements:

    - enabled_categories: None uses DEFAULT_ENABLED_CATEGORIES; an empty
      set disables all detection; otherwise only the given categories
      are detected.
    - operators: maps entity type to an anonymization operator among
      "replace", "mask", and "redact". Entity types without an operator
      entry use the Presidio default (replace with the entity label).
      None applies the Presidio default to every detected entity.
    """

    enabled_categories: Optional[Set[str]] = None
    operators: Optional[Dict[str, str]] = None
    mask_char: str = "*"
    analyzer_language: str = "en"

    def __post_init__(self) -> None:
        if self.enabled_categories is not None and (
            not isinstance(self.enabled_categories, set)
            or not all(isinstance(category, str) for category in self.enabled_categories)
        ):
            raise ValueError("enabled_categories must be a set of strings or None")

        if self.operators is not None:
            if not isinstance(self.operators, dict):
                raise ValueError("operators must be a dictionary or None")
            if not all(isinstance(entity_type, str) for entity_type in self.operators):
                raise ValueError("operator entity types must be strings")
            unknown = set(self.operators.values()) - SUPPORTED_OPERATORS
            if unknown:
                raise ValueError(
                    f"Unsupported anonymization operators: {sorted(unknown)}; "
                    f"supported operators are {sorted(SUPPORTED_OPERATORS)}"
                )

        if not isinstance(self.mask_char, str) or len(self.mask_char) != 1:
            raise ValueError("mask_char must be a single character")

        if not isinstance(self.analyzer_language, str) or not self.analyzer_language:
            raise ValueError("analyzer_language must be a non-empty string")


class PiiGuardService:
    """Sanitizes text by detecting and anonymizing configured PII.

    Stateless content transformation: no persistence, no tenant or
    identity awareness, and no authorization decisions. Instances are
    cheap and reusable.

    The Presidio engines are created lazily on first use and can be
    injected for testing.
    """

    def __init__(
        self,
        config: Optional[PiiGuardConfig] = None,
        analyzer_engine: Any = None,
        anonymizer_engine: Any = None,
    ):
        self.config = config if config is not None else PiiGuardConfig()
        self._analyzer_engine = analyzer_engine
        self._anonymizer_engine = anonymizer_engine

    def sanitize(self, text: str) -> PiiResult:
        """Sanitize input text and return the result.

        Args:
            text: The text to sanitize. Must be a string.

        Returns:
            PiiResult with the sanitized text and the detections that
            were found and handled.

        Raises:
            TypeError: If text is not a string.
            PiiGuardError: If analysis or anonymization fails. The
                service never returns unsanitized text as a successful
                result.
        """
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        if not text:
            return PiiResult(sanitized_text=text)

        if self.config.enabled_categories is not None and not self.config.enabled_categories:
            return PiiResult(sanitized_text=text)

        analyzer_results = self._analyze(text)
        if not analyzer_results:
            return PiiResult(sanitized_text=text)

        anonymized_text = self._anonymize(text, analyzer_results)

        detections = [
            PiiDetection(
                entity_type=result.entity_type,
                start=result.start,
                end=result.end,
                score=result.score,
            )
            for result in analyzer_results
        ]
        return PiiResult(sanitized_text=anonymized_text, detections=detections)

    def _analyze(self, text: str) -> Any:
        entities = self._entity_filter()
        try:
            return self._analyzer().analyze(
                text=text,
                language=self.config.analyzer_language,
                entities=entities,
            )
        except Exception as exc:
            raise PiiGuardError("PII analysis failed") from exc

    def _anonymize(self, text: str, analyzer_results: Any) -> str:
        operators = self._operators(analyzer_results)
        try:
            engine_result = self._anonymizer().anonymize(
                text=text,
                analyzer_results=analyzer_results,
                operators=operators,
            )
        except Exception as exc:
            raise PiiGuardError("PII anonymization failed") from exc
        return engine_result.text

    def _entity_filter(self) -> Optional[List[str]]:
        if self.config.enabled_categories is None:
            return sorted(DEFAULT_ENABLED_CATEGORIES)
        return sorted(self.config.enabled_categories)

    def _operators(self, analyzer_results: Any) -> Optional[Dict[str, Any]]:
        if not self.config.operators:
            return None

        from presidio_anonymizer.entities import OperatorConfig

        operators: Dict[str, Any] = {}
        for entity_type in {result.entity_type for result in analyzer_results}:
            operator_name = self.config.operators.get(entity_type)
            if operator_name is None:
                continue
            if operator_name == "replace":
                operators[entity_type] = OperatorConfig(
                    "replace", {"new_value": f"<{entity_type}>"}
                )
            elif operator_name == "mask":
                operators[entity_type] = OperatorConfig(
                    "mask",
                    {
                        "masking_char": self.config.mask_char,
                        # Covers the maximum realistic PII value length
                        # so the whole value is masked.
                        "chars_to_mask": MASK_MAX_CHARS,
                        "from_end": False,
                    },
                )
            elif operator_name == "redact":
                operators[entity_type] = OperatorConfig("redact", None)
        return operators or None

    def _analyzer(self) -> Any:
        if self._analyzer_engine is None:
            from presidio_analyzer import AnalyzerEngine

            self._analyzer_engine = AnalyzerEngine()
        return self._analyzer_engine

    def _anonymizer(self) -> Any:
        if self._anonymizer_engine is None:
            from presidio_anonymizer import AnonymizerEngine

            self._anonymizer_engine = AnonymizerEngine()
        return self._anonymizer_engine
