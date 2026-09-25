"""The spaCy model behind PII detection: pinned default, measured recall.

``en_core_web_lg`` is ~445 MB and is the single largest contributor to the
container image. ``en_core_web_sm`` is ~15 MB, and since nothing in
``pii.py`` reads word vectors or similarity — the capability lg adds — the
small model looks like an obvious saving.

It is not taken, and these tests are why. PERSON is the only entity type the
spaCy model affects; every other category in ``DEFAULT_ENABLED_CATEGORIES``
is a pattern or checksum recognizer. A PERSON miss means personal data
reaches embeddings, stored chunks and LLM prompts unredacted, which is the
failure this service exists to prevent.

The full PII suite (94 tests) passes on BOTH models, so it cannot settle the
question: only a handful of those tests mention PERSON and they use simple
Anglo names. The recall test below uses a name x context matrix instead, and
that is where the models separate.
"""

import os

import pytest

from arc.services.pii import _DEFAULT_SPACY_MODEL, PiiGuardService

# Deliberately varied: given names and surnames from several naming
# traditions, because NER degradation is not uniformly distributed and a
# corpus of Anglo names would hide exactly the regression that matters.
NAMES = [
    "Sarah Johnson",
    "Michael Chen",
    "Priya Raghunathan",
    "Juan Carlos Rodriguez",
    "Wei Zhang",
    "Aisha Abdullah",
    "Nnamdi Okonkwo",
    "Hiroshi Tanaka",
    "Fatima Al-Rashid",
    "Ingrid Johansson",
]

# Sentence shapes taken from the kind of text ARC actually ingests: incident
# notes, ticket updates, chat lines, terse field labels.
CONTEXTS = [
    "Please contact {} about the incident report.",
    "Escalate to {} on the SRE rota.",
    "{} approved the deployment.",
    "The ticket was reassigned to {} yesterday.",
    "cc {} on the incident channel",
    "Owner: {}",
    "Reviewed by {} and the security team.",
    "{} requested temporary access to production.",
]

# Measured for en_core_web_lg at 79/80. The floor sits just below that so an
# ordinary model refresh does not fail the build, while a switch to a
# materially weaker model (sm measured 77/80) does.
MIN_PERSON_RECALL = 0.975


def _person_recall(guard: PiiGuardService):
    """Return (recall, missed_cases) over the name x context matrix."""
    missed = []
    total = 0
    for context in CONTEXTS:
        for name in NAMES:
            total += 1
            text = context.format(name)
            spans = [r for r in guard._analyze(text) if r.entity_type == "PERSON"]
            if not spans:
                missed.append(text)
    return (total - len(missed)) / total, missed


class TestDefaultModel:
    def test_default_is_the_large_model(self):
        """The default must not drift to the small model without evidence.

        Changing this constant is a security decision, not a size
        optimisation. If it changes, ``test_person_recall_meets_floor``
        below has to still pass on the new default.
        """
        assert _DEFAULT_SPACY_MODEL == "en_core_web_lg"

    def test_model_is_configurable(self, monkeypatch):
        """PII_SPACY_MODEL must actually reach Presidio.

        Presidio's default provider hardcodes en_core_web_lg, so an engine
        built without an explicit configuration would ignore the env var
        silently — a knob that looks like it works and does not is worse
        than no knob.
        """
        monkeypatch.setenv("PII_SPACY_MODEL", "en_core_web_lg")
        guard = PiiGuardService()
        engine = guard._analyzer().nlp_engine
        loaded = getattr(engine, "nlp", {})
        assert "en" in loaded, "the configured model was not loaded for English"

    def test_empty_model_name_fails_closed(self, monkeypatch):
        from arc.services.pii import PiiGuardError

        monkeypatch.setenv("PII_SPACY_MODEL", "   ")
        guard = PiiGuardService()
        with pytest.raises(PiiGuardError):
            guard._analyzer()


class TestPersonRecall:
    def test_person_recall_meets_floor(self):
        """The shipped default must clear the measured recall floor.

        This is the test that would fail if someone swapped in the small
        model for the disk saving.
        """
        guard = PiiGuardService()
        recall, missed = _person_recall(guard)
        assert recall >= MIN_PERSON_RECALL, (
            f"PERSON recall {recall:.1%} is below the {MIN_PERSON_RECALL:.1%} "
            f"floor with model {os.getenv('PII_SPACY_MODEL', _DEFAULT_SPACY_MODEL)!r}. "
            f"Missed: {missed}"
        )

    @pytest.mark.skipif(
        not os.getenv("ARC_COMPARE_SPACY_MODELS"),
        reason=(
            "comparison requires en_core_web_sm installed alongside lg; "
            "opt in with ARC_COMPARE_SPACY_MODELS=1"
        ),
    )
    def test_small_model_is_measurably_worse(self, monkeypatch):
        """Documents the regression that keeps the large model as default.

        Opt-in because it needs both models present. It exists so the
        decision is reproducible rather than a claim in a commit message.
        """
        monkeypatch.setenv("PII_SPACY_MODEL", "en_core_web_lg")
        lg_recall, _ = _person_recall(PiiGuardService())
        monkeypatch.setenv("PII_SPACY_MODEL", "en_core_web_sm")
        sm_recall, sm_missed = _person_recall(PiiGuardService())

        assert sm_recall < lg_recall, (
            "en_core_web_sm no longer underperforms en_core_web_lg on this "
            f"matrix (sm {sm_recall:.1%}, lg {lg_recall:.1%}). If a model "
            "update closed the gap, re-measure and reconsider the default — "
            "the saving is ~430 MB."
        )
        assert sm_missed, "expected the small model to miss at least one PERSON"
