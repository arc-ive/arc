import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plug, RefreshCw, Plus } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import {
  listConnectors,
  createConnector,
  syncConnector,
} from '../../api/endpoints/connectors.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
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
      <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-zinc-100 mb-4">Create Connector</h3>
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
    <div className="flex flex-col gap-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <PageHeader title="Connectors"
          description="External integrations for this tenant." />
            </div>
          </div>
        </div>
        {canCreate && (
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="size-4" />
            New Connector
          </Button>
        )}
      </section>

      <CreateConnectorDialog open={showCreate} onClose={() => setShowCreate(false)} />

      {isLoading && <Spinner />}
      {error && <ErrorState error={error} />}

      {!isLoading && !error && (!connectors || connectors.length === 0) && (
        <EmptyState
          icon={Plug}
          title="No connectors configured"
          description="Connectors sync knowledge from external sources like GitHub, Slack, or Linear."
          action={canCreate && <Button onClick={() => setShowCreate(true)}><Plus className="size-4" /> Create connector</Button>}
        />
      )}

      {!isLoading && !error && connectors && connectors.length > 0 && (
        <>
          {syncMutation.isError && (
            <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 px-3.5 py-3 text-[13px] text-amber-200/80">
              <p className="font-semibold">Sync failed</p>
              {isCredentialError ? (
                <p className="mt-1">
                  Connector credentials are not configured on this deployment.
                  An administrator must set the <code className="font-mono text-amber-300/80">CONNECTOR_CREDENTIALS</code> environment
                  variable before sync can run.
                </p>
              ) : (
                <p className="mt-1">{errorMessage(syncError)}</p>
              )}
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {connectors.map((connector) => (
            <Card key={connector.id} className="flex flex-col gap-3 p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-zinc-100">{connector.name}</p>
                <Badge variant={connector.status === 'active' ? 'green' : 'neutral'} size="sm">
                  {connector.status}
                </Badge>
              </div>
              <p className="text-[13px] text-fg-muted">Provider: {connector.provider}</p>
              {connector.target && (
                <p className="font-mono text-xs text-zinc-400">Target: {connector.target}</p>
              )}
              <p className="text-xs text-fg-muted">
                Created: {new Date(connector.created_at).toLocaleDateString()}
              </p>
              <div className="mt-auto flex items-center gap-2 pt-2">
                {canSync && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => syncMutation.mutate(connector.id)}
                    disabled={syncMutation.isPending}
                  >
                    <RefreshCw className="size-3.5" />
                    Sync
                  </Button>
                )}
              </div>
            </Card>
          ))}
          </div>
        </>
      )}
    </div>
  )
}
