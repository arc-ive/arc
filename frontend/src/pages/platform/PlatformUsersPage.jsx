import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, UserPlus } from 'lucide-react'
import { createUser } from '../../api/endpoints/users.js'
import { errorMessage } from '../../api/errors.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

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
      queryClient.invalidateQueries({ queryKey: ['users'] })
      onClose()
      setForm({ id: '', email: '', username: '', status: 'active' })
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const handleClose = () => {
    if (mutation.isPending) return
    onClose()
    setError(null)
  }

  const canSubmit =
    form.id.trim() && form.email.trim() && !mutation.isPending

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Create user"
      description="Provision a platform user. Requires the user:create permission."
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
          <p className="rounded-lg border border-red-900/50 bg-red-950/20 px-3 py-2.5 text-[13px] text-red-300">
            {error}
          </p>
        )}
      </div>
    </Dialog>
  )
}

export function PlatformUsersPage() {
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
            Users
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Platform-level user provisioning.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setCreateOpen(true)}>
          <UserPlus className="size-4" />
          New user
        </Button>
      </section>

      <Card>
        <CardHeader
          title="Platform user directory"
          description="There is no global user listing endpoint yet."
        />
        <CardContent>
          <div className="flex flex-col items-start gap-3">
            <div className="flex items-center gap-2">
              <Badge variant="indigo">
                <ShieldCheck className="mr-1 size-3" />
                user:create — platform administrators
              </Badge>
            </div>
            <p className="max-w-2xl text-[13px] leading-relaxed text-zinc-500">
              Creating a user here provisions an identity the backend will
              accept. Application roles are assigned through the backend
              configuration (APPLICATION_ROLE_ASSIGNMENTS), and tenant
              membership is provisioned separately. To list or manage users
              inside a tenant, open the tenant&apos;s{' '}
              <span className="text-zinc-300">Users</span> page.
            </p>
          </div>
        </CardContent>
      </Card>

      <CreateUserDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}