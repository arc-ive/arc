import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Plus } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import {
  listConnectors,
  createConnector,
  syncConnector,
} from '../../api/endpoints/connectors.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { Button } from '../../components/ui/Button.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { errorMessage } from '../../api/errors.js'

const PROVIDERS = [
  { value: 'github', label: 'GitHub', targetHint: 'owner/repo (e.g. arc-ive/arc)' },
  { value: 'slack', label: 'Slack', targetHint: 'channel name (e.g. general)' },
  { value: 'linear', label: 'Linear', targetHint: 'team key (e.g. ENG)' },
]

function CreateConnectorDialog({ open, onClose }) {
  const queryClient = useQueryClient()
  const { tenantId } = useTenant()
  const [provider, setProvider] = useState('github')
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [error, setError] = useState(null)

  const createMutation = useMutation({
    mutationFn: (data) => createConnector(tenantId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.connectors(tenantId) })
      onClose()
      setProvider('github')
      setName('')
      setTarget('')
      setError(null)
    },
    onError: (err) => setError(err),
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    setError(null)
    createMutation.mutate({ provider, name, target })
  }

  const selectedProvider = PROVIDERS.find((p) => p.value === provider)

  return (
    <Dialog open={open} onClose={onClose}>
      <div className="w-full max-w-md rounded-xl border border-line bg-surface-overlay p-6 shadow-xl">
        <h2 className="text-lg font-semibold text-fg mb-4">Create Connector</h2>
        {error && (
          <InlineError className="mb-4">
            {errorMessage(error)}
          </InlineError>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <Select
            label="Provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={createMutation.isPending}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </Select>
          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Main GitHub integration"
            required
            disabled={createMutation.isPending}
          />
          <Input
            label="Target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder={selectedProvider?.targetHint ?? 'Provider-specific target'}
            required
            disabled={createMutation.isPending}
            hint={selectedProvider?.targetHint}
          />
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={onClose} disabled={createMutation.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending || !name.trim() || !target.trim()}>
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </div>
        </form>
      </div>
    </Dialog>
  )
}

export function ConnectorsPage() {
  useDocumentTitle('Sources')
  const { tenantId } = useTenant()
  const queryClient = useQueryClient()
  const { can } = useCapabilities()
  const canCreate = can('connector:create')
  const canSync = can('connector:sync')
  const [showCreate, setShowCreate] = useState(false)

  const { data: connectors, isLoading, error } = useQuery({
    queryKey: queryKeys.connectors(tenantId),
    queryFn: () => listConnectors(tenantId),
    enabled: Boolean(tenantId),
  })

  const syncMutation = useMutation({
    mutationFn: (connectorId) => syncConnector(tenantId, connectorId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.connectors(tenantId) })
    },
  })

  const syncError = syncMutation.error
  const syncErrorDetail = syncError?.response?.data?.detail || ''
  const isCredentialError = syncError?.response?.status === 500 &&
    (syncErrorDetail.includes('credential') || syncErrorDetail.includes('not configured') || syncErrorDetail.includes('synchronization failed'))

  return (
    <div className="flex flex-col">
      {/* A person comes here to answer one question: is knowledge still
          arriving from the systems we connected? So each connector is a
          line that says what it is, where it points and whether it is
          live — and sync is the action, sitting on that line. */}
      <header className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <h1 className="type-display-lg text-fg">Sources</h1>
          {!isLoading && connectors?.length > 0 && (
            <p className="mt-2 text-[14px] text-fg-muted">
              {connectors.length}{' '}
              {connectors.length === 1 ? 'system' : 'systems'} Arc reads company
              knowledge from
            </p>
          )}
        </div>
        {canCreate && (
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="size-4" />
            Connect a system
          </Button>
        )}
      </header>

      <CreateConnectorDialog open={showCreate} onClose={() => setShowCreate(false)} />

      {isLoading && (
        <div className="mt-8 flex flex-col gap-4 border-t border-line pt-6">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-6 w-64" />
        </div>
      )}
      {error && <div className="mt-8"><ErrorState error={error} /></div>}

      {!isLoading && !error && (!connectors || connectors.length === 0) && (
        <div className="measure mt-8 border-t border-line pt-6">
          <p className="type-prose text-fg-subtle">
            Nothing is connected yet.
          </p>
          <p className="mt-2 text-[14px] leading-relaxed text-fg-muted">
            Connect GitHub, Slack or Linear and Arc will read documents from
            them into the Company Brain.
          </p>
          {canCreate && (
            <Button className="mt-5" onClick={() => setShowCreate(true)}>
              <Plus className="size-4" /> Connect a system
            </Button>
          )}
        </div>
      )}

      {!isLoading && !error && connectors?.length > 0 && (
        <>
          {syncMutation.isError && (
            <InlineError className="mt-8">
              <p className="font-medium text-fg">That sync did not run.</p>
              {isCredentialError ? (
                <p className="mt-1">
                  Credentials for this connector are not configured on this
                  deployment. An administrator has to set them before a sync
                  can run.
                </p>
              ) : (
                <p className="mt-1">{errorMessage(syncError)}</p>
              )}
            </InlineError>
          )}

          {syncMutation.isSuccess && syncMutation.data && (
            <p className="mt-8 border-l-2 border-success pl-4 text-[14px] text-fg-subtle">
              Synced{' '}
              <span className="font-medium text-fg">
                {syncMutation.data.items_fetched}
              </span>{' '}
              {syncMutation.data.items_fetched === 1 ? 'item' : 'items'} into the
              Company Brain.
            </p>
          )}

          <ul className="mt-8 border-t border-line">
            {connectors.map((connector) => (
              <li
                key={connector.id}
                className="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-line py-5"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="type-display text-[1.25rem] leading-snug text-fg">
                      {connector.name}
                    </h2>
                    <Badge
                      variant={connector.status === 'active' ? 'success' : 'neutral'}
                      size="sm"
                      dot
                    >
                      {connector.status}
                    </Badge>
                  </div>
                  {/* Provider and target on one line. They were three
                      stacked rows reading "Provider: slack", "Target:
                      general", "Created: 17/09/2026" — a label per value
                      for values that fit on one. */}
                  <p className="type-data mt-1 text-fg-muted">
                    {connector.provider}
                    {connector.target && ` · ${connector.target}`}
                  </p>
                </div>

                {canSync && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => syncMutation.mutate(connector.id)}
                    disabled={syncMutation.isPending}
                    isLoading={
                      syncMutation.isPending &&
                      syncMutation.variables === connector.id
                    }
                    loadingText="Syncing…"
                  >
                    <RefreshCw className="size-3.5" />
                    Sync now
                  </Button>
                )}
              </li>
            ))}
          </ul>

          {/* Stated rather than implied: the record carries no last-sync
              time, so the page cannot claim one. */}
          <p className="measure mt-5 text-[12.5px] leading-relaxed text-fg-muted">
            Arc does not record when a source last synced, so this list shows
            whether a connection is live, not when it last ran.
          </p>
        </>
      )}
    </div>
  )
}
