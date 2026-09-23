import { useCallback, useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { cn } from '../../lib/cn.js'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Building2, Plus } from 'lucide-react'
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
          <InlineError>
            {error}
          </InlineError>
        )}
      </div>
    </Dialog>
  )
}

export function PlatformTenantsPage() {
  const [createOpen, setCreateOpen] = useState(false)
  const handleCloseCreate = useCallback(() => setCreateOpen(false), [])

  const userTenants = useQuery({
    queryKey: queryKeys.platformTenants,
    queryFn: () => getPlatformTenants(),
    staleTime: 30 * 1000,
  })

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <PageHeader title="Tenants"
          description="Every workspace on this Arc platform." />
        </div>
        <Button variant="secondary" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" />
          New tenant
        </Button>
      </section>

      {userTenants.isPending && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {userTenants.isError && (
        <Card>
          <ErrorState
            title="Could not load tenants"
            message={errorMessage(userTenants.error)}
            onRetry={() => userTenants.refetch()}
            error={userTenants.error}
          />
        </Card>
      )}

      {userTenants.data?.length === 0 && (
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

      {/* A real link per row, not a div with role="link" and an Enter-only
          key handler: that gave no href, so no middle-click, no
          open-in-new-tab, no context menu. */}
      {userTenants.data?.length > 0 && (
        <section className="stagger border-t border-line">
          {userTenants.data.map((tenant) => (
            <Link
              key={tenant.id}
              to={`/platform/tenants/${encodeURIComponent(tenant.id)}`}
              className={cn(
                'group grid grid-cols-1 items-baseline gap-x-8 gap-y-1 border-b border-line py-4',
                'transition-colors duration-150 hover:bg-surface-sunk/60',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
                'sm:grid-cols-[minmax(0,1fr)_10rem_9rem_1.5rem]',
              )}
            >
              <span className="min-w-0">
                <span className="type-display block truncate text-[1.25rem] leading-snug text-fg">
                  {tenant.name}
                </span>
                <span className="type-data mt-0.5 block truncate text-fg-muted">
                  {tenant.id}
                </span>
              </span>
              <span>
                <Badge variant={tenant.status === 'active' ? 'success' : 'neutral'} dot size="sm">
                  {tenant.status}
                </Badge>
              </span>
              <span className="text-[12.5px] text-fg-muted">
                Created {formatDate(tenant.created_at)}
              </span>
              <ArrowUpRight className="hidden size-4 shrink-0 text-fg-muted transition-transform duration-150 group-hover:-translate-y-0.5 group-hover:text-fg sm:block" />
            </Link>
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