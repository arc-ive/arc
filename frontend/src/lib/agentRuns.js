/**
 * Why an agent run ended, in words a reader can act on.
 *
 * `error_kind` is the backend's own identifier. The page was rendering it
 * verbatim — "Reason: agent_decision_unavailable" — which ARC_UX_SPEC.md §1
 * rules out, and which tells an operator nothing about what to do next.
 *
 * The sentences below come from the services that emit each kind, not from
 * guesses. `agent_decision_unavailable` in particular is documented in
 * src/arc/services/agent.py: the default deterministic provider carries no
 * decision script, so the Agent fails closed until a decision capability is
 * configured. That is a configuration state, not a fault, and reads very
 * differently to an operator than a bare identifier does.
 */
const REASONS = {
  agent_decision_unavailable:
    'No decision capability is configured, so the agent stopped rather than guess.',
  agent_capability_unavailable:
    'Agent runs are not enabled for this workspace.',
  requires_human_approval:
    'A step needs a human decision before it can run.',
  approval_consumption_failed:
    'The approval could not be applied — it may have expired or already been used.',
  authorization_denied: 'The run was not permitted to do what it attempted.',
  not_allowed: 'The run attempted something outside its allowed tools.',
  unknown_tool: 'The run referenced a tool that is not registered.',
  invalid_input: 'The run was given input it could not use.',
  invalid_policy_metadata: 'A policy on this run is misconfigured.',
  invalid_permission_metadata: 'A permission on this run is misconfigured.',
  execution_error: 'A step failed while running.',
  retryable_error: 'A step failed for a reason that may clear on its own.',
  timeout: 'A step took too long and was stopped.',
  transport_error: 'Arc could not reach a service the run needed.',
  server_error: 'A service the run needed returned an error.',
  client_error: 'A service the run needed rejected the request.',
  max_steps_reached:
    'The run hit its step limit and stopped. Agent runs are bounded by design.',
}

/**
 * A sentence for an error kind.
 *
 * Unknown kinds are de-slugged rather than dropped or shown raw: a reader
 * gets "Some new failure" instead of `some_new_failure`, and nothing is
 * hidden when the backend adds a kind this map has not caught up with.
 */
export function runFailureReason(errorKind) {
  const raw = String(errorKind ?? '').trim()
  if (!raw) return null
  if (REASONS[raw]) return REASONS[raw]
  const words = raw.replace(/[_-]+/g, ' ').trim()
  if (!words) return null
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}.`
}

/** True when the kind is one this build has a sentence for. */
export function isKnownFailureKind(errorKind) {
  return Object.prototype.hasOwnProperty.call(REASONS, String(errorKind ?? ''))
}
