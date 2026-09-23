import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApprovalTimeline } from './ApprovalTimeline.jsx'

const hoursAgo = (n) => new Date(Date.now() - n * 3_600_000).toISOString()
const hoursAhead = (n) => new Date(Date.now() + n * 3_600_000).toISOString()

function approval(overrides = {}) {
  return {
    id: 'appr-1',
    tool_name: 'grant_temporary_access',
    risk_level: 'high',
    status: 'pending',
    requester_user_id: 'ref-acme-technologies-ops-user',
    created_at: hoursAgo(3),
    expires_at: hoursAhead(21),
    decided_at: null,
    decided_by_user_id: null,
    consumed_at: null,
    ...overrides,
  }
}

describe('ApprovalTimeline', () => {
  it('never presents an approved action as having run', () => {
    // V2-ADR-012, "Approval Is Not Authorization". The previous page showed
    // a green "approved" badge and nothing else — a reader could reasonably
    // conclude the action had happened. `consumed_at` is what says it ran.
    render(
      <ApprovalTimeline
        approval={approval({
          status: 'approved',
          decided_at: hoursAgo(2),
          decided_by_user_id: 'ref-acme-technologies-company-admin',
        })}
      />,
    )
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(screen.getByText('Not run yet')).toBeInTheDocument()
    expect(
      screen.getByText(/approving authorises the action — the requester still runs it/),
    ).toBeInTheDocument()
  })

  it('says the action ran only once it was consumed', () => {
    render(
      <ApprovalTimeline
        approval={approval({
          status: 'consumed',
          decided_at: hoursAgo(48),
          decided_by_user_id: 'ref-acme-technologies-company-admin',
          consumed_at: hoursAgo(47),
        })}
      />,
    )
    expect(screen.getByText('Run')).toBeInTheDocument()
    expect(screen.getByText('the requester ran the action')).toBeInTheDocument()
  })

  it('closes the run step when the decision was a rejection', () => {
    // A rejected request is finished. Leaving the last step open would read
    // as "still might happen".
    render(<ApprovalTimeline approval={approval({ status: 'rejected', decided_at: hoursAgo(1), decided_by_user_id: 'ref-acme-technologies-company-admin' })} />)
    expect(screen.getByText('Rejected')).toBeInTheDocument()
    expect(screen.getByText('the action will not run')).toBeInTheDocument()
  })

  it('tells a pending approver how long the window is', () => {
    // The expiry is the only clock that matters on a pending request, and
    // it was not on the page at all.
    render(<ApprovalTimeline approval={approval({ expires_at: hoursAhead(20) })} />)
    expect(screen.getByText('Awaiting decision')).toBeInTheDocument()
    expect(screen.getByText(/expires in about 20 hours/)).toBeInTheDocument()
  })

  it('says so when the window has already closed', () => {
    render(<ApprovalTimeline approval={approval({ expires_at: hoursAgo(1) })} />)
    expect(screen.getByText('the window has closed')).toBeInTheDocument()
  })

  it('addresses the requester in the second person', () => {
    render(<ApprovalTimeline approval={approval()} viewerIsRequester />)
    expect(screen.getByText('by you')).toBeInTheDocument()
  })

  it('shortens another person’s user id rather than printing it raw', () => {
    // Ids are tenant-prefixed and long; the tail is what distinguishes one
    // person from another.
    render(<ApprovalTimeline approval={approval()} />)
    expect(screen.getByText('by ops user')).toBeInTheDocument()
    expect(screen.queryByText(/ref-acme-technologies/)).not.toBeInTheDocument()
  })

  it('reads as an ordered list for assistive technology', () => {
    render(<ApprovalTimeline approval={approval()} />)
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
  })
})
