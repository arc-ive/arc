import { describe, it, expect } from 'vitest'
import { runFailureReason, isKnownFailureKind } from './agentRuns.js'

describe('runFailureReason', () => {
  it('explains the default failure instead of echoing its identifier', () => {
    // The page rendered "Reason: agent_decision_unavailable". That is the
    // backend's own key, and it is the single most common terminal state in
    // a default install — src/arc/services/agent.py fails the agent closed
    // when no decision capability is configured. An operator seeing the raw
    // key cannot tell that this is configuration rather than breakage.
    const reason = runFailureReason('agent_decision_unavailable')
    expect(reason).toMatch(/no decision capability is configured/i)
    expect(reason).not.toContain('_')
  })

  it('distinguishes the capability gate from the decision gate', () => {
    // agent.py calls these out as distinct states, so they must not
    // collapse into one message.
    expect(runFailureReason('agent_capability_unavailable')).not.toBe(
      runFailureReason('agent_decision_unavailable'),
    )
  })

  it('says a bounded run hit its bound, not that it failed', () => {
    // V2-ADR-013 makes the agent bounded by design. "Max steps reached" is
    // the design working, and the wording should not read as a fault.
    expect(runFailureReason('max_steps_reached')).toMatch(/bounded by design/i)
  })

  it('never shows a raw identifier for a kind it does not know', () => {
    // The backend can add a kind before this map catches up. De-slugging
    // keeps the information while keeping the identifier off the screen —
    // dropping it would hide why a run ended.
    expect(runFailureReason('some_new_backend_kind')).toBe('Some new backend kind.')
    expect(isKnownFailureKind('some_new_backend_kind')).toBe(false)
  })

  it('returns null when a run ended cleanly', () => {
    expect(runFailureReason(null)).toBeNull()
    expect(runFailureReason('')).toBeNull()
    expect(runFailureReason(undefined)).toBeNull()
  })
})
