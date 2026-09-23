/**
 * Presentation helpers for approval requests.
 *
 * The approval record is a machine record: `tool_name` is the registry key
 * (`grant_temporary_access`), and `input_summary` is a JSON object. Both
 * were being rendered verbatim — the tool key as the card's heading, in
 * snake_case, which is exactly the kind of implementation identifier
 * ARC_UX_SPEC.md §2 rules out of the UI.
 *
 * Nothing in the contract carries a human label for a tool, so the label is
 * derived here rather than blocking on a backend field.
 */

/**
 * A human label for a tool.
 *
 * `grant_temporary_access` → `Grant temporary access`. Only the first word
 * is capitalised: these read as actions, and title-casing every word turns
 * a sentence into a product name.
 */
export function toolLabel(toolName) {
  const raw = String(toolName ?? '').trim()
  if (!raw) return 'Unnamed action'
  const words = raw.replace(/[-_.]+/g, ' ').replace(/\s+/g, ' ').trim()
  if (!words) return 'Unnamed action'
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * The requester's own words about why they asked.
 *
 * `input_summary` arrives as a JSON object (sometimes already parsed,
 * sometimes as a string). Its values are what a person wrote; its keys are
 * argument names. Showing `{"justification": "..."}` shows the reader the
 * braces and the field name, neither of which is the point.
 */
export function formatSummary(summary) {
  if (summary == null) return ''
  if (typeof summary !== 'string') {
    return Object.values(summary).filter(Boolean).join(' · ')
  }
  try {
    const parsed = JSON.parse(summary)
    if (parsed && typeof parsed === 'object') {
      return Object.values(parsed).filter(Boolean).join(' · ')
    }
  } catch {
    // Not JSON — the server sent a plain sentence, which is already the
    // thing we want. Fall through.
  }
  return summary
}
