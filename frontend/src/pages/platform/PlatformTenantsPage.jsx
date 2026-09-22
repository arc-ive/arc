import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Building2, Plus } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { createTenant, getPlatformTenants } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { SkeletonCard } from '../../components/ui/Skeleton.jsx'
import { formatDate } from '../../lib/format.js'

function CreateTenantDialog({ open, onClose }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ id: '', name: '', status: 'active' })
  const [error, setError] = useState(null)

  const mutation = useMutation({
    mutationFn: () => createTenant(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.platformTenants })
      onClose()
      setForm({ id: '', name: '', status: 'active' })
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const handleClose = useCallback(() => {
    if (mutation.isPending) return
    onClose()
    setError(null)
  }, [mutation.isPending, onClose])

  const canSubmit = form.id.trim() && form.name.trim() && !mutation.isPending

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Create tenant"
      description="Create a new customer workspace. Platform administrators only."
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
            Create tenant
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Input
          label="Tenant ID"
          required
          placeholder="acme-it"
          value={form.id}
          onChange={(e) => setForm({ ...form, id: e.target.value })}
          disabled={mutation.isPending}
          hint="Stable identifier used in URLs and APIs."
        />
        <Input
          label="Name"
          required
          placeholder="Acme IT Services"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
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

export function PlatformTenantsPage() {
  const { isDemo } = useAuth()
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)
  const handleCloseCreate = useCallback(() => setCreateOpen(false), [])

  const userTenants = useQuery({
    queryKey: queryKeys.platformTenants,
    queryFn: () => getPlatformTenants(),
    enabled: !isDemo,
    staleTime: 30 * 1000,
  })

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
            Tenants
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Platform-level tenant administration. Tenant boundaries are
            enforced by the backend.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setCreateOpen(true)} disabled={isDemo}>
          <Plus className="size-4" />
          New tenant
        </Button>
      </section>

      {isDemo && (
        <Card>
          <EmptyState
            icon={Building2}
            title="Demo Mode — backend data unavailable"
            description="No tenant data is fetched in Demo Mode. Sign in with a real session to load tenants."
          />
        </Card>
      )}

      {!isDemo && userTenants.isPending && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {!isDemo && userTenants.isError && (
        <Card>
          <ErrorState
            title="Could not load tenants"
            message={errorMessage(userTenants.error)}
            onRetry={() => userTenants.refetch()}
            error={userTenants.error}
          />
        </Card>
      )}

      {!isDemo && userTenants.data?.length === 0 && (
        <Card>
          <EmptyState
            icon={Building2}
            title="No tenants yet"
            description="No tenants have been created yet. Create one to get started."
            action={
              <Button variant="secondary" onClick={() => setCreateOpen(true)}>
                <Plus className="size-4" />
                Create tenant
              </Button>
            }
          />
        </Card>
      )}

      {!isDemo && userTenants.data?.length > 0 && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {userTenants.data.map((tenant) => (
            <Card
              key={tenant.id}
              hover
              className="group flex cursor-pointer flex-col gap-3 p-5"
              onClick={() =>
                navigate(`/platform/tenants/${encodeURIComponent(tenant.id)}`)
              }
              role="link"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  navigate(`/platform/tenants/${encodeURIComponent(tenant.id)}`)
                }
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-500 transition-colors duration-150 group-hover:text-indigo-400">
                  <Building2 className="size-4.5" />
                </div>
                <Badge variant={tenant.status === 'active' ? 'green' : 'neutral'} dot>
                  {tenant.status}
                </Badge>
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-zinc-100">
                  {tenant.name}
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-zinc-600">
                  {tenant.id}
                </p>
              </div>
              <div className="mt-auto flex items-center justify-between">
                <span className="text-xs text-zinc-600">
                  Created {formatDate(tenant.created_at)}
                </span>
                <ArrowUpRight className="size-4 text-zinc-600 transition-colors duration-150 group-hover:text-zinc-300" />
              </div>
            </Card>
          ))}
        </section>
      )}

      <CreateTenantDialog
        open={createOpen}
        onClose={handleCloseCreate}
      />
    </div>
  )
}