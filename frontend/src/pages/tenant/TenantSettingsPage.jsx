import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { getTenant, updateTenant } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Badge } from '../../components/ui/Badge.jsx'

export function TenantSettingsPage() {
  const { tenantId } = useParams()
  const { isDemo, principal } = useAuth()
  const { can } = useCapabilities()
  const queryClient = useQueryClient()
  const canUpdate = can('tenant:update')

  const tenantQuery = useQuery({
    queryKey: queryKeys.tenant(tenantId),
    queryFn: () => getTenant(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })

  const [form, setForm] = useState(null)
  const [saved, setSaved] = useState(false)

  const updateMutation = useMutation({
    mutationFn: (payload) => updateTenant(tenantId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.tenant(tenantId), data)
      queryClient.invalidateQueries({ queryKey: queryKeys.tenant(tenantId) })
      // Company and Overview read the tenant from the user-tenants list, whose
      // key is not a prefix of the tenant key and is therefore untouched above.
      queryClient.invalidateQueries({
        queryKey: queryKeys.userTenants(principal?.sub),
      })
      setForm(null)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  if (isDemo) {
    return (
      <div className="flex flex-col gap-6">
        <section>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
              <Settings className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
              <p className="mt-1 text-sm text-zinc-500">Tenant configuration and preferences.</p>
            </div>
          </div>
        </section>
        <Card>
          <CardContent>
            <p className="py-8 text-center text-sm text-zinc-500">
              Settings require a backend session. Sign in with a real JWT to view tenant configuration.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (tenantQuery.isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <section>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
              <Settings className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
              <p className="mt-1 text-sm text-zinc-500">Tenant configuration and preferences.</p>
            </div>
          </div>
        </section>
        <Spinner />
      </div>
    )
  }

  if (tenantQuery.error) {
    return (
      <div className="flex flex-col gap-6">
        <section>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
              <Settings className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
              <p className="mt-1 text-sm text-zinc-500">Tenant configuration and preferences.</p>
            </div>
          </div>
        </section>
        <ErrorState error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />
      </div>
    )
  }

  const tenant = tenantQuery.data

  const handleChange = (field) => (e) => {
    setForm((prev) => ({
      ...(prev ?? {
        name: tenant.name,
        industry: tenant.industry ?? '',
        address: tenant.address ?? '',
        phone: tenant.phone ?? '',
        website: tenant.website ?? '',
        logo_url: tenant.logo_url ?? '',
      }),
      [field]: e.target.value,
    }))
    setSaved(false)
  }

  const handleSave = () => {
    const payload = {
      name: form?.name ?? tenant.name,
      industry: form?.industry ?? tenant.industry ?? '',
      address: form?.address ?? tenant.address ?? '',
      phone: form?.phone ?? tenant.phone ?? '',
      website: form?.website ?? tenant.website ?? '',
      logo_url: form?.logo_url ?? tenant.logo_url ?? '',
    }
    updateMutation.mutate(payload)
  }

  const handleCancel = () => {
    setForm(null)
    setSaved(false)
  }

  const current = form ?? {
    name: tenant.name,
    industry: tenant.industry ?? '',
    address: tenant.address ?? '',
    phone: tenant.phone ?? '',
    website: tenant.website ?? '',
    logo_url: tenant.logo_url ?? '',
  }

  const hasChanges = form !== null

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Settings className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Settings</h1>
            <p className="mt-1 text-sm text-zinc-500">Tenant configuration and preferences.</p>
          </div>
        </div>
      </section>

      <Card>
        <CardHeader
          title="Company Profile"
          description="Basic information about this tenant organization."
        />
        <CardContent>
          <div className="flex flex-col gap-4 max-w-xl">
            <Input
              label="Company Name"
              value={current.name}
              onChange={handleChange('name')}
              disabled={!canUpdate}
              required
            />
            <Input
              label="Industry"
              placeholder="e.g. Technology, Healthcare, Finance"
              value={current.industry}
              onChange={handleChange('industry')}
              disabled={!canUpdate}
            />
            <Textarea
              label="Address"
              placeholder="Street address, city, state, zip code"
              value={current.address}
              onChange={handleChange('address')}
              disabled={!canUpdate}
              rows={3}
            />
            <Input
              label="Phone"
              placeholder="+1 (555) 123-4567"
              value={current.phone}
              onChange={handleChange('phone')}
              disabled={!canUpdate}
            />
            <Input
              label="Website"
              placeholder="https://example.com"
              value={current.website}
              onChange={handleChange('website')}
              disabled={!canUpdate}
            />
            <Input
              label="Logo URL"
              placeholder="https://example.com/logo.png"
              value={current.logo_url}
              onChange={handleChange('logo_url')}
              disabled={!canUpdate}
            />
          </div>

          {canUpdate && (
            <div className="flex items-center gap-3 mt-6">
              <Button
                onClick={handleSave}
                disabled={!hasChanges || updateMutation.isPending}
                isLoading={updateMutation.isPending}
                loadingText="Saving…"
              >
                Save changes
              </Button>
              {hasChanges && (
                <Button variant="secondary" onClick={handleCancel} disabled={updateMutation.isPending}>
                  Cancel
                </Button>
              )}
              {saved && (
                <Badge variant="green" size="sm">Saved</Badge>
              )}
              {updateMutation.isError && (
                <span className="text-xs text-red-400">{errorMessage(updateMutation.error)}</span>
              )}
            </div>
          )}

          {!canUpdate && (
            <p className="mt-4 text-xs text-zinc-500">
              You do not have permission to modify tenant configuration. Contact a company administrator.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center gap-1.5 text-xs text-zinc-600">
        <Settings className="size-3.5" />
        Changes are authorized by the backend on every request.
      </div>
    </div>
  )
}
