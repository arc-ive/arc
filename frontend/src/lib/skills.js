/**
 * Skill vocabulary shared by the create and edit forms.
 *
 * `risk` is a closed enum on the contract — `SkillRiskLevel` in
 * domain/models.py is exactly `low | medium | high`, and the API rejects
 * anything else:
 *
 *     POST ~/skills  {"risk": "High"}      → 422
 *     POST ~/skills  {"risk": "critical"}  → 422
 *     POST ~/skills  {"risk": "high"}      → 200
 *
 * The form shipped a free-text input with the placeholder
 * "e.g. low, medium, high", so the capitalised spelling a person would
 * naturally type was a server-side validation failure. A closed set of
 * three belongs in a select.
 */

/**
 * The risk levels, with what each one means.
 *
 * The hints matter because `risk` is easy to confuse with the separate
 * `approval_required` gate. V2-ADR-011 keeps them apart: risk feeds the
 * deterministic execution policy layer, and the SkillRiskLevel docstring
 * says it "does NOT create an approval mapping".
 */
export const RISK_LEVELS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
]

const RISK_LABELS = new Map(RISK_LEVELS.map((r) => [r.value, r.label]))

/** A readable label for a stored risk value; unknown values are shown as-is. */
export function riskLabel(value) {
  if (!value) return null
  return RISK_LABELS.get(String(value).toLowerCase()) ?? String(value)
}

/** Badge tone for a risk level. Unknown values stay neutral. */
export function riskTone(value) {
  switch (String(value ?? '').toLowerCase()) {
    case 'high':
      return 'danger'
    case 'medium':
      return 'warning'
    case 'low':
      return 'neutral'
    default:
      return 'neutral'
  }
}
