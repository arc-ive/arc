import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, UserPlus, Users } from 'lucide-react'
import {
  createTenantMembership,
  deleteTenantMembership,
} from '../../api/endpoints/memberships.js'
import { getTenantUsers } from '../../api/endpoints/users.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card } from '../../components/ui/Card.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Avatar } from '../../components/ui/Avatar.jsx'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '../../components/ui/Table.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
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
  const { tenantId } = useParams()
  const [addOpen, setAddOpen] = useState(false)
  const [removeTarget, setRemoveTarget] = useState(null)

  const users = useQuery({
    queryKey: queryKeys.tenantUsers(tenantId),
    queryFn: () => getTenantUsers(tenantId),
    enabled: Boolean(tenantId),
  })

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <PageHeader title="Tenant users"
          description="Users with membership in this tenant, as authorized by the backend." />
        </div>
        <Button
          variant="secondary"
          onClick={() => setAddOpen(true)}
        >
          <UserPlus className="size-4" />
          Add member
        </Button>
      </section>

      {users.isPending && (
        <Card className="p-5">
          <div className="flex flex-col gap-4">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="size-8 rounded-full" />
                <div className="flex flex-1 flex-col gap-1.5">
                  <Skeleton className="h-3.5 w-1/3" />
                  <Skeleton className="h-3 w-1/4" />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {users.isError && (
        <Card>
          <ErrorState
            title="Could not load tenant users"
            message={errorMessage(users.error)}
            onRetry={() => users.refetch()}
            error={users.error}
          />
        </Card>
      )}

      {users.data?.length === 0 && (
        <Card>
          <EmptyState
            icon={Users}
            title="No users in this tenant"
            description="No user has been assigned to this tenant yet. Click 'Add member' to provision a membership."
          />
        </Card>
      )}

      {users.data?.length > 0 && (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Username</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <Avatar name={user.email} size="sm" />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-zinc-100">
                          {user.email}
                        </p>
                        <p className="truncate font-mono text-xs text-fg-muted">
                          {user.id}
                        </p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-zinc-400">
                    {user.username ?? '—'}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={user.status === 'active' ? 'green' : 'neutral'}
                      size="sm"
                      dot
                    >
                      {user.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-fg-muted">
                    {formatDate(user.created_at)}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setRemoveTarget(user)}
                      title="Remove member"
                    >
                      <Trash2 className="size-4 text-fg-muted hover:text-red-400" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
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
