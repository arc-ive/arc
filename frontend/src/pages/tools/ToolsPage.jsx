import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Wrench, Play, CheckCircle } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import { listTools, executeTool } from '../../api/endpoints/tools.js'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { errorMessage } from '../../api/errors.js'
import { STALLED_MESSAGE, isQueryFailed, isQueryLoading } from '../../api/queryState.js'

function ToolExecuteDialog({ tool, open, onClose }) {
  const { tenantId } = useTenant()
  const [inputJson, setInputJson] = useState('{}')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const executeMutation = useMutation({
    mutationFn: ({ name, input }) => executeTool(tenantId, name, input),
    onSuccess: (data) => {
      setResult(data)
      setError(null)
    },
    onError: (err) => {
      setError(err)
      setResult(null)
    },
  })

  const handleExecute = () => {
    setError(null)
    setResult(null)
    try {
      const parsed = JSON.parse(inputJson)
      executeMutation.mutate({ name: tool.name, input: parsed })
    } catch {
      setError(new Error('Invalid JSON input'))
    }
  }

  const handleClose = () => {
    setInputJson('{}')
    setResult(null)
    setError(null)
    onClose()
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-xl max-h-[80vh] overflow-y-auto">
        <h3 className="text-lg font-semibold text-zinc-100 mb-1">Execute Tool</h3>
        <p className="text-sm text-zinc-500 mb-4">{tool.name} — {tool.description}</p>

        {tool.input_schema && (
          <div className="mb-4 p-3 rounded-lg bg-zinc-800/50 border border-zinc-700">
            <p className="text-xs font-medium text-zinc-400 mb-2">Input Schema</p>
            <pre className="text-xs text-zinc-300 overflow-x-auto">{JSON.stringify(tool.input_schema, null, 2)}</pre>
          </div>
        )}

        <div className="mb-4">
          <label className="block text-sm font-medium text-zinc-300 mb-1">Input (JSON)</label>
          <textarea
            value={inputJson}
            onChange={(e) => setInputJson(e.target.value)}
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 font-mono focus:border-indigo-500 focus:outline-none"
            rows={6}
            disabled={executeMutation.isPending}
          />
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-900/50 bg-red-950/20 px-3.5 py-3 text-[13px] text-red-300">
            {errorMessage(error)}
          </div>
        )}

        {result && (
          <div className="mb-4 rounded-lg border border-green-900/50 bg-green-950/20 p-3.5">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle className="size-4 text-green-400" />
              <span className="text-sm font-medium text-green-300">Execution successful</span>
            </div>
            <pre className="text-xs text-zinc-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result.output, null, 2)}</pre>
          </div>
        )}

        <div className="flex justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={executeMutation.isPending}>
            Close
          </Button>
          <Button onClick={handleExecute} disabled={executeMutation.isPending}>
            <Play className="size-4" />
            {executeMutation.isPending ? 'Executing...' : 'Execute'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ToolsPage() {
  const { tenantId } = useTenant()
  const { isDemo } = useAuth()
  const { can } = useCapabilities()
  const canExecute = can('tool:execute')
  const [executeTarget, setExecuteTarget] = useState(null)

  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(tenantId),
    queryFn: () => listTools(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })
  const tools = toolsQuery.data
  const isLoading = isQueryLoading(toolsQuery)
  // Issue #225: a failed-and-parked query is a failure, not loading.
  const failed = isQueryFailed(toolsQuery)
  const error = toolsQuery.error

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Wrench className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Tools</h1>
            <p className="mt-1 text-sm text-zinc-500">Platform-owned AI tools available for this tenant.</p>
          </div>
        </div>
      </section>

      <ToolExecuteDialog
        tool={executeTarget}
        open={Boolean(executeTarget)}
        onClose={() => setExecuteTarget(null)}
      />

      {isLoading && <Spinner />}
      {failed && (
        <ErrorState
          error={error}
          message={error ? undefined : STALLED_MESSAGE}
          onRetry={() => toolsQuery.refetch()}
        />
      )}

      {!isLoading && !failed && (!tools || tools.length === 0) && (
        <EmptyState
          icon={Wrench}
          title="No tools available"
          description="Tools are registered by the platform and available for agent execution."
        />
      )}

      {!isLoading && !failed && tools && tools.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {tools.map((tool) => (
            <Card key={tool.name} className="flex flex-col gap-3 p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-zinc-100">{tool.name}</p>
                <Badge
                  variant={
                    tool.risk_level === 'high' ? 'red' :
                    tool.risk_level === 'medium' ? 'amber' : 'green'
                  }
                  size="sm"
                >
                  {tool.risk_level}
                </Badge>
              </div>
              <p className="text-[13px] text-zinc-500">{tool.description || 'No description'}</p>
              {tool.required_permissions && tool.required_permissions.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tool.required_permissions.map((perm) => (
                    <Badge key={perm} variant="neutral" size="sm">{perm}</Badge>
                  ))}
                </div>
              )}
              <div className="text-xs text-zinc-600">v{tool.version}</div>
              <div className="mt-auto pt-2">
                {canExecute && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setExecuteTarget(tool)}
                  >
                    <Play className="size-3.5" />
                    Execute
                  </Button>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
