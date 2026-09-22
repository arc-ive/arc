import { useState, useCallback } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserPlus, Users } from 'lucide-react'
import {
  createUser,
  listPlatformUsers,
} from '../../api/endpoints/users.js'
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

export function PlatformUsersPage() {
  const [createOpen, setCreateOpen] = useState(false)

  const handleCloseCreate = useCallback(() => {
    setCreateOpen(false)
  }, [])

  const users = useQuery({
    queryKey: queryKeys.platformUsers(),
    queryFn: listPlatformUsers,
  })

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <PageHeader title="Users"
          description="Platform-level user directory. All provisioned users are listed       here regardless of tenant membership." />
        </div>
        <Button
          variant="secondary"
          onClick={() => setCreateOpen(true)}
        >
          <UserPlus className="size-4" />
          New user
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
            title="Could not load users"
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
            title="No users provisioned yet"
            description="Click 'New user' to provision the first platform user."
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <CreateUserDialog
        open={createOpen}
        onClose={handleCloseCreate}
      />
    </div>
  )
}
