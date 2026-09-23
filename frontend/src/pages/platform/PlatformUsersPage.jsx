import { useState, useCallback } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, UserPlus } from 'lucide-react'
import {
  createUser,
  listPlatformUsers,
} from '../../api/endpoints/users.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Button } from '../../components/ui/Button.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Section } from '../../components/layout/Section.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { formatDate } from '../../lib/format.js'

function CreateUserDialog({ open, onClose }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    id: '',
    email: '',
    username: '',
    status: 'active',
  })
  const [error, setError] = useState(null)

  const mutation = useMutation({
    mutationFn: () =>
      createUser({
        id: form.id.trim(),
        email: form.email.trim(),
        username: form.username.trim() || null,
        status: form.status,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.platformUsers() })
      onClose()
      setForm({ id: '', email: '', username: '', status: 'active' })
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const handleClose = useCallback(() => {
    if (mutation.isPending) return
    onClose()
    setError(null)
  }, [mutation.isPending, onClose])

  const canSubmit =
    form.id.trim() && form.email.trim() && !mutation.isPending

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Create user"
      description="Add a user to the Arc platform."
      footer={
        <>
          <Button variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            isLoading={mutation.isPending}
            loadingText="Creating…"
            disabled={!canSubmit}
          >
            Create user
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Input
          label="User ID"
          required
          placeholder="u_acme_admin"
          value={form.id}
          onChange={(e) => setForm({ ...form, id: e.target.value })}
          disabled={mutation.isPending}
          hint="This must match the JWT sub claim used to authenticate."
        />
        <Input
          label="Email"
          required
          type="email"
          placeholder="admin@acme.example"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          disabled={mutation.isPending}
        />
        <Input
          label="Username"
          placeholder="admin"
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          disabled={mutation.isPending}
        />
        <Select
          label="Status"
          value={form.status}
          onChange={(e) => setForm({ ...form, status: e.target.value })}
          disabled={mutation.isPending}
        >
          <option value="active">active</option>
          <option value="suspended">suspended</option>
        </Select>
        {error && (
          <InlineError>
            {error}
          </InlineError>
        )}
      </div>
    </Dialog>
  )
}

/**
 * The platform directory.
 *
 * `GET /platform/users` returns `id, email, username, status, created_at`
 * — no role, and no workspace. A flat list of those five fields is an
 * exported table, not a directory: an administrator's question is almost
 * always "who is in which workspace", and the endpoint cannot answer it
 * alone.
 *
 * I tried composing it from `/platform/tenants` + `/tenants/{id}/users`.
 * That does not work, and the reason is architectural rather than
 * incidental:
 *
 *     GET /tenants/ref-acme-technologies/users
 *     403  {"detail":"Access to the requested tenant is denied"}
 *
 * A platform administrator is not a member of any tenant. V2-ADR-003
 * makes platform administration and tenant membership separate, and the
 * tenant user list requires tenant permission — so Arc will not tell this
 * administrator who is in a workspace, by design. The first version of
 * this page fired one request per workspace, had every one refused, and
 * then reported "17 in no workspace", which is a false statement about
 * the data rather than an honest gap.
 *
 * So the directory shows what this endpoint actually knows, says what it
 * cannot know and why, and does not guess. Deriving the workspace from
 * the email domain would "work" against the reference data and be
 * fabrication anywhere else.
 *
 * Role is likewise not available from any endpoint reachable here.
 */
const ROLE_ORDER = ['owner', 'member', 'viewer']

/** One person inside a company, or in the no-workspace group. */
function PersonRow({ user }) {
  return (
    <li className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line py-3.5 transition-colors duration-150 hover:bg-surface-sunk/70">
      <Avatar name={user.username || user.email} size="sm" />

      <div className="min-w-0 flex-1">
        <p className="truncate text-[14.5px] font-medium text-fg">
          {user.username || user.email}
        </p>
        {/* Only when it adds something: a person with no display name
            would otherwise have their email printed twice, stacked. */}
        {user.username && (
          <p className="truncate text-[12.5px] text-fg-muted">{user.email}</p>
        )}
      </div>

      {user.role && (
        <span className="type-label shrink-0 text-fg-muted">{user.role}</span>
      )}

      {user.status !== 'active' && (
        <Badge variant="neutral" size="sm" dot>
          {user.status}
        </Badge>
      )}

      <span className="hidden shrink-0 text-[12.5px] text-fg-muted lg:block">
        Joined {formatDate(user.created_at)}
      </span>
    </li>
  )
}

const ROLE_FILTERS = [
  { value: null, label: 'Everyone' },
  { value: 'owner', label: 'Owners' },
  { value: 'member', label: 'Members' },
  { value: 'viewer', label: 'Viewers' },
]

/**
 * Everyone on the platform, organised by the company they belong to.
 *
 * This was one flat list of every person across every customer, which is
 * unreadable the moment there is more than one customer: four companies
 * of four people read as sixteen strangers.
 *
 * `/platform/users` now returns each person's memberships with the
 * tenant name and role, so the page groups by company and a platform
 * administrator can see the shape of the customer base rather than a
 * directory dump.
 *
 * Membership is platform administration metadata, not tenant content:
 * ADR-008 already lets a platform administrator CREATE memberships for
 * any user in any tenant, so reading them is strictly less privileged.
 * Tenant content -- knowledge, approvals, skills -- is still unreachable
 * from here, and opening a workspace is still the way to see inside one.
 */
export function PlatformUsersPage() {
  useDocumentTitle('People')
  const [createOpen, setCreateOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [role, setRole] = useState(null)

  const handleCloseCreate = useCallback(() => setCreateOpen(false), [])

  const users = useQuery({
    queryKey: queryKeys.platformUsers(),
    queryFn: listPlatformUsers,
  })

  const people = users.data ?? []
  const needle = query.trim().toLowerCase()

  const matchesSearch = (u) =>
    !needle ||
    (u.username ?? '').toLowerCase().includes(needle) ||
    (u.email ?? '').toLowerCase().includes(needle)

  // Group by company. A person with two memberships appears under both,
  // because that is true and hiding one would misrepresent their access.
  const companies = new Map()
  const unaffiliated = []

  for (const person of people) {
    if (!matchesSearch(person)) continue
    const memberships = (person.memberships ?? []).filter(
      (m) => !role || m.role === role,
    )
    if (memberships.length === 0) {
      // Only unaffiliated when they have no memberships at all — not
      // when a role filter excluded the ones they have.
      if ((person.memberships ?? []).length === 0 && !role) {
        unaffiliated.push(person)
      }
      continue
    }
    for (const m of memberships) {
      if (!companies.has(m.tenant_id)) {
        companies.set(m.tenant_id, { name: m.tenant_name, people: [] })
      }
      companies.get(m.tenant_id).people.push({ ...person, role: m.role })
    }
  }

  const grouped = [...companies.entries()].sort((a, b) =>
    a[1].name.localeCompare(b[1].name),
  )
  const shownCount =
    grouped.reduce((n, [, c]) => n + c.people.length, 0) + unaffiliated.length
  const inactive = people.filter((u) => u.status !== 'active').length

  return (
    <div className="flex flex-col">
      <header className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <h1 className="type-display-lg text-fg">People</h1>
          {!users.isPending && (
            <p className="mt-2 text-[14px] text-fg-muted">
              {people.length} provisioned across {companies.size}{' '}
              {companies.size === 1 ? 'workspace' : 'workspaces'}
              {inactive > 0 ? ` · ${inactive} not active` : ''}
            </p>
          )}
        </div>
        <Button variant="secondary" onClick={() => setCreateOpen(true)}>
          <UserPlus className="size-4" />
          New user
        </Button>
      </header>

      {/* Search and the workspace filter answer the two questions an
          administrator actually arrives with: find this person, or show
          me who is in this workspace. */}
      <div className="mt-8 flex flex-col gap-4 border-b border-line pb-4 lg:flex-row lg:items-center lg:gap-8">
        <div className="relative min-w-0 lg:w-[24rem]">
          <Search className="pointer-events-none absolute left-0 top-1/2 size-4 -translate-y-1/2 text-fg-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find someone by name or email"
            aria-label="Find someone on the platform"
            className="h-10 w-full border-0 bg-transparent pl-7 text-[15px] text-fg placeholder:text-fg-muted focus-visible:outline-none"
          />
        </div>

        <div className="flex flex-wrap gap-1">
          {ROLE_FILTERS.map((f) => (
            <button
              key={f.value ?? 'all'}
              onClick={() => setRole(f.value)}
              aria-pressed={role === f.value}
              className={`rounded px-2.5 py-1 text-[13px] transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 ${
                role === f.value
                  ? 'text-fg underline decoration-fg-muted decoration-1 underline-offset-[6px]'
                  : 'text-fg-muted hover:text-fg-subtle'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {users.isPending && (
        <div className="mt-6 flex flex-col gap-5">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="size-9 rounded-full" />
              <span className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-4 w-44" />
                <Skeleton className="h-3 w-64" />
              </span>
            </div>
          ))}
        </div>
      )}

      {users.isError && (
        <div className="mt-8">
          <ErrorState
            title="Could not load the platform directory"
            message={errorMessage(users.error)}
            onRetry={() => users.refetch()}
            error={users.error}
          />
        </div>
      )}

      {/* Both groups share one gate. Nesting the no-workspace group
          inside the company groups meant a platform whose users have no
          memberships yet -- a fresh deployment, or before anyone is
          assigned -- rendered an empty page while holding users. */}
      {!users.isPending && (grouped.length > 0 || unaffiliated.length > 0) && (
        <div className="mt-2 flex flex-col gap-12">
          {grouped.map(([tenantId, company]) => (
            <Section
              key={tenantId}
              title={company.name}
              actions={
                <span className="text-[12.5px] text-fg-muted">
                  {company.people.length}{' '}
                  {company.people.length === 1 ? 'person' : 'people'}
                </span>
              }
            >
              <ul className="stagger border-t border-line">
                {company.people
                  .slice()
                  .sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role))
                  .map((user) => (
                    <PersonRow key={`${tenantId}-${user.id}`} user={user} />
                  ))}
              </ul>
            </Section>
          ))}

          {unaffiliated.length > 0 && (
            <Section
              title="No workspace"
              description="Provisioned on the platform but not a member of any workspace. Platform administrators sit here by design — administering Arc does not make you a member of a customer's workspace."
            >
              <ul className="stagger border-t border-line">
                {unaffiliated.map((user) => (
                  <PersonRow key={user.id} user={user} />
                ))}
              </ul>
            </Section>
          )}
        </div>
      )}

      {!users.isPending && !users.isError && people.length === 0 && (
        <p className="measure mt-8 type-prose text-fg-subtle">
          Nobody has been provisioned on this platform yet.
        </p>
      )}

      {!users.isPending && people.length > 0 && shownCount === 0 && (
        <p className="mt-8 text-[14px] text-fg-muted">
          Nobody matches that search.
        </p>
      )}

      <CreateUserDialog open={createOpen} onClose={handleCloseCreate} />
    </div>
  )
}

