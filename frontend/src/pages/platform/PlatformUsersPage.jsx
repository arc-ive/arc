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
export function PlatformUsersPage() {
  useDocumentTitle('People')
  const [createOpen, setCreateOpen] = useState(false)
  const [query, setQuery] = useState('')

  const handleCloseCreate = useCallback(() => setCreateOpen(false), [])

  const users = useQuery({
    queryKey: queryKeys.platformUsers(),
    queryFn: listPlatformUsers,
  })

  const people = users.data ?? []
  const needle = query.trim().toLowerCase()

  const shown = needle
    ? people.filter(
        (u) =>
          (u.username ?? '').toLowerCase().includes(needle) ||
          (u.email ?? '').toLowerCase().includes(needle),
      )
    : people

  const inactive = people.filter((u) => u.status !== 'active').length

  return (
    <div className="flex flex-col">
      <header className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <h1 className="type-display-lg text-fg">People</h1>
          {!users.isPending && (
            <p className="mt-2 text-[14px] text-fg-muted">
              {people.length} provisioned
              {inactive > 0 ? ` · ${inactive} not active` : ' · all active'}
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

      {!users.isPending && shown.length > 0 && (
        <ul className="stagger">
          {shown.map((user) => {
            return (
              <li
                key={user.id}
                className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line py-4 transition-colors duration-150 hover:bg-surface-sunk/70"
              >
                <Avatar name={user.username || user.email} size="md" />

                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] font-medium text-fg">
                    {user.username || user.email}
                  </p>
                  {/* Only when it adds something: a person with no display
                      name would otherwise have their email printed twice,
                      stacked. */}
                  {user.username && (
                    <p className="truncate text-[13px] text-fg-muted">{user.email}</p>
                  )}
                </div>

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
          })}
        </ul>
      )}

      {!users.isPending && !users.isError && people.length === 0 && (
        <p className="measure mt-8 type-prose text-fg-subtle">
          Nobody has been provisioned on this platform yet.
        </p>
      )}

      {!users.isPending && people.length > 0 && shown.length === 0 && (
        <p className="mt-8 text-[14px] text-fg-muted">
          Nobody matches that search.
        </p>
      )}

      <p className="measure mt-6 text-[12.5px] leading-relaxed text-fg-muted">
        Arc keeps platform administration separate from workspace
        membership, so this directory cannot show which workspaces someone
        belongs to or what role they hold there. Open a workspace to see
        its people.
      </p>

      <CreateUserDialog open={createOpen} onClose={handleCloseCreate} />
    </div>
  )
}

