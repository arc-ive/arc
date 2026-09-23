import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { getTenant, updateTenant } from '../../api/endpoints/tenants.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { Input } from '../../components/ui/Input.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'

export function TenantSettingsPage() {
  useDocumentTitle('Settings')
  const { tenantId } = useParams()
  const { principal } = useAuth()
  const { can } = useCapabilities()
  const queryClient = useQueryClient()
  const canUpdate = can('tenant:update')

  const tenantQuery = useQuery({
    queryKey: queryKeys.tenant(tenantId),
    queryFn: () => getTenant(tenantId),
    enabled: Boolean(tenantId),
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

  // The heading is identical in all three states. It previously rendered
  // as a PageHeader while loading and as a display heading once the tenant
  // arrived, so the title visibly changed size underneath the reader.
  if (tenantQuery.isLoading) {
    return (
      <div className="flex flex-col">
        <h1 className="type-display-lg text-fg">Settings</h1>
        <div className="mt-12 flex flex-col gap-10">
          {Array.from({ length: 2 }, (_, group) => (
            <div key={group} className="border-t border-line pt-8">
              <Skeleton className="h-3 w-24" />
              <div className="mt-6 flex max-w-xl flex-col gap-5">
                {Array.from({ length: 3 }, (_, field) => (
                  <div key={field} className="flex flex-col gap-1.5">
                    <Skeleton className="h-3.5 w-28" />
                    <Skeleton className="h-9 w-full" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (tenantQuery.error) {
    return (
      <div className="flex flex-col">
        <h1 className="type-display-lg text-fg">Settings</h1>
        <div className="mt-10">
          <ErrorState
            title="Could not load this workspace's settings"
            error={tenantQuery.error}
            onRetry={() => tenantQuery.refetch()}
          />
        </div>
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
    /* Settings is the quietest surface in Arc. A person is here to change
       one field and leave, so it is a two-column sheet: what the group is
       on the left, the fields on the right. No cards, no animation —
       motion on a form someone is editing is interference.

       Grouped by intent rather than by the shape of the record: who the
       company is, and how to reach them. */
    <div className="flex flex-col">
      <header className="min-w-0">
        <h1 className="type-display-lg text-fg">Settings</h1>
        <p className="measure mt-2 text-[14px] text-fg-muted">
          How this workspace is named and reached. These details appear
          wherever Arc refers to the company.
        </p>
      </header>

      <form
        className="mt-10 flex flex-col gap-12"
        onSubmit={(e) => {
          e.preventDefault()
          if (canUpdate && hasChanges) handleSave()
        }}
      >
        <SettingsGroup
          title="Identity"
          description="How this workspace is named across Arc."
        >
          <Input
            label="Company name"
            value={current.name}
            onChange={handleChange('name')}
            disabled={!canUpdate}
            required
          />
          <Input
            label="Industry"
            placeholder="Technology"
            value={current.industry}
            onChange={handleChange('industry')}
            disabled={!canUpdate}
          />
          <Input
            label="Logo URL"
            placeholder="https://example.com/logo.png"
            value={current.logo_url}
            onChange={handleChange('logo_url')}
            disabled={!canUpdate}
          />
        </SettingsGroup>

        <SettingsGroup
          title="Contact"
          description="Where people reach this company."
        >
          <Input
            label="Website"
            placeholder="https://example.com"
            value={current.website}
            onChange={handleChange('website')}
            disabled={!canUpdate}
          />
          <Input
            label="Phone"
            placeholder="+1 (555) 123-4567"
            value={current.phone}
            onChange={handleChange('phone')}
            disabled={!canUpdate}
          />
          <Textarea
            label="Address"
            value={current.address}
            onChange={handleChange('address')}
            disabled={!canUpdate}
            rows={3}
          />
        </SettingsGroup>

        {canUpdate ? (
          /* The save bar only exists when there is something to save.
             A permanently visible disabled button is furniture. */
          hasChanges && (
            <div className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t border-line bg-canvas/95 py-4 backdrop-blur-sm">
              <Button
                type="submit"
                disabled={updateMutation.isPending}
                isLoading={updateMutation.isPending}
                loadingText="Saving…"
              >
                Save changes
              </Button>
              <Button
                variant="secondary"
                type="button"
                onClick={handleCancel}
                disabled={updateMutation.isPending}
              >
                Discard
              </Button>
              {updateMutation.isError && (
                <span className="text-[13px] text-danger">
                  {errorMessage(updateMutation.error)}
                </span>
              )}
            </div>
          )
        ) : (
          <p className="measure text-[13.5px] leading-relaxed text-fg-muted">
            These settings are read-only for you. A company administrator can
            change them.
          </p>
        )}

        {saved && !hasChanges && (
          <p className="text-[13.5px] text-success" role="status">
            Saved.
          </p>
        )}
      </form>
    </div>
  )
}

/**
 * One group of settings.
 *
 * The label sits beside its fields rather than above them, so the eye can
 * run down the left edge to find a group without reading every field.
 */
function SettingsGroup({ title, description, children }) {
  return (
    <section className="grid gap-x-16 gap-y-5 border-t border-line pt-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <div className="min-w-0">
        <h2 className="type-label text-fg-muted">{title}</h2>
        {description && (
          <p className="measure-tight mt-2 text-[13px] leading-relaxed text-fg-muted">
            {description}
          </p>
        )}
      </div>
      <div className="flex max-w-xl flex-col gap-5">{children}</div>
    </section>
  )
}
