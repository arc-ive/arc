import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, Trash2, UserPlus } from 'lucide-react'
import {
  createTenantMembership,
  deleteTenantMembership,
} from '../../api/endpoints/memberships.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Button } from '../../components/ui/Button.jsx'
import { IconButton } from '../../components/ui/IconButton.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { Avatar } from '../../components/ui/Avatar.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { formatDate } from '../../lib/format.js'

function AddMemberDialog({ open, onClose, tenantId }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ user_id: '', role: 'member' })
  const [error, setError] = useState(null)

  const mutation = useMutation({
    mutationFn: () =>
      createTenantMembership(tenantId, {
        user_id: form.user_id.trim(),
        role: form.role,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.tenantUsers(tenantId),
      })
      onClose()
      setForm({ user_id: '', role: 'member' })
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const handleClose = () => {
    if (mutation.isPending) return
    onClose()
    setError(null)
  }

  const canSubmit = form.user_id.trim() && !mutation.isPending

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Add member"
      description="Add a person to this workspace."
      footer={
        <>
          <Button variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            isLoading={mutation.isPending}
            loadingText="Adding…"
            disabled={!canSubmit}
          >
            Add member
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Input
          label="User ID"
          required
          placeholder="u_acme_admin"
          value={form.user_id}
          onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          disabled={mutation.isPending}
          hint="The user must already exist. This must match the JWT sub claim."
        />
        <Select
          label="Role"
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
          disabled={mutation.isPending}
        >
          <option value="member">member</option>
          <option value="owner">owner</option>
          <option value="viewer">viewer</option>
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

function ConfirmRemoveDialog({ open, onClose, tenantId, user }) {
  const queryClient = useQueryClient()
  const [error, setError] = useState(null)

  const mutation = useMutation({
    mutationFn: () => deleteTenantMembership(tenantId, user.id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.tenantUsers(tenantId),
      })
      onClose()
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const handleClose = () => {
    if (mutation.isPending) return
    onClose()
    setError(null)
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Remove member"
      description={`Remove ${user.email} from this tenant? This action cannot be undone.`}
      footer={
        <>
          <Button variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => mutation.mutate()}
            isLoading={mutation.isPending}
            loadingText="Removing…"
          >
            Remove member
          </Button>
        </>
      }
    >
      {error && (
        <InlineError>
          {error}
        </InlineError>
      )}
    </Dialog>
  )
}

export function TenantUsersPage() {
  useDocumentTitle('People')
  const { tenantId } = useParams()
  const [addOpen, setAddOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState(null)

  const users = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: Boolean(tenantId),
  })

  const [query, setQuery] = useState('')

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
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0">
          <h1 className="type-display-lg text-fg">People</h1>
          {/* The count and its one exception, rather than a sentence
              restating the page title. */}
          {!users.isPending && people.length > 0 && (
            <p className="mt-2 text-[14px] text-fg-muted">
              {people.length} {people.length === 1 ? 'person' : 'people'}
              {inactive > 0 ? ` · ${inactive} not active` : ' · all active'}
            </p>
          )}
        </div>
        <Button variant="secondary" onClick={() => setAddOpen(true)}>
          <UserPlus className="size-4" />
          Add member
        </Button>
      </header>

      {people.length > 4 && (
        <div className="relative mt-8">
          <Search className="pointer-events-none absolute left-0 top-1/2 size-4 -translate-y-1/2 text-fg-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find someone"
            aria-label="Find someone in this workspace"
            className="h-11 w-full border-b border-line bg-transparent pl-7 text-[15px] text-fg placeholder:text-fg-muted focus:border-fg focus-visible:outline-none"
          />
        </div>
      )}

      {users.isPending && (
        <div className="mt-8 flex flex-col gap-5 border-t border-line pt-5">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="size-9 rounded-full" />
              <span className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-64" />
              </span>
            </div>
          ))}
        </div>
      )}

      {users.isError && (
        <div className="mt-8">
          <ErrorState
            title="Could not load the people in this workspace"
            message={errorMessage(users.error)}
            onRetry={() => users.refetch()}
            error={users.error}
          />
        </div>
      )}

      {!users.isPending && people.length === 0 && (
        <p className="measure mt-8 border-t border-line pt-6 type-prose text-fg-subtle">
          Nobody has been given access to this workspace yet.
        </p>
      )}

      {shown.length > 0 && (
        <ul className="stagger mt-8 border-t border-line">
          {shown.map((user) => (
            <li
              key={user.id}
              className="group flex items-center gap-4 border-b border-line py-4 transition-colors duration-150 hover:bg-surface-sunk/70"
            >
              <Avatar name={user.username || user.email} size="md" />
              <div className="min-w-0 flex-1">
                {/* A person's name leads; their address is how you reach
                    them, not who they are. The id — which was printed in
                    mono under every row — is a database key. */}
                <p className="truncate text-[15px] font-medium text-fg">
                  {user.username || user.email}
                </p>
                <p className="truncate text-[13px] text-fg-muted">{user.email}</p>
              </div>

              {user.status !== 'active' && (
                <Badge variant="neutral" size="sm" dot>
                  {user.status}
                </Badge>
              )}

              <span className="hidden shrink-0 text-[12.5px] text-fg-muted sm:block">
                Joined {formatDate(user.created_at)}
              </span>

              {/* The destructive action stays out of the way until the row
                  is under the pointer or the button is focused. */}
              <IconButton
                variant="danger"
                size="sm"
                onClick={() => setRemoveTarget(user)}
                label={`Remove ${user.username || user.email}`}
                className="opacity-0 transition-opacity duration-150 focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Trash2 className="size-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      )}

      {needle && shown.length === 0 && (
        <p className="mt-8 border-t border-line pt-6 text-[14px] text-fg-muted">
          Nobody here matches “{query}”.
        </p>
      )}

      <AddMemberDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        tenantId={tenantId}
      />

      {removeTarget && (
        <ConfirmRemoveDialog
          open={Boolean(removeTarget)}
          onClose={() => setRemoveTarget(null)}
          tenantId={tenantId}
          user={removeTarget}
        />
      )}
    </div>
  )
}
