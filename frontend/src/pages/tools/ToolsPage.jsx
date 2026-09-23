import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Wrench, Play, CheckCircle } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import { listTools, executeTool } from '../../api/endpoints/tools.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Card } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
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
      <div className="w-full max-w-lg rounded-xl border border-line bg-surface-overlay p-6 shadow-xl max-h-[80vh] overflow-y-auto">
        <h2 className="text-lg font-semibold text-fg mb-1">Execute Tool</h2>
        <p className="text-sm text-fg-muted mb-4">{tool.name} — {tool.description}</p>

        {tool.input_schema && (
          <div className="mb-4 p-3 rounded-lg bg-surface-overlay border border-line-strong">
            <p className="text-xs font-medium text-fg-muted mb-2">Input Schema</p>
            <pre className="text-xs text-fg-subtle overflow-x-auto">{JSON.stringify(tool.input_schema, null, 2)}</pre>
          </div>
        )}

        <Textarea
          className="mb-4"
          label="Input (JSON)"
          value={inputJson}
          onChange={(e) => setInputJson(e.target.value)}
          textareaClassName="font-mono"
          rows={6}
          spellCheck={false}
          disabled={executeMutation.isPending}
        />

        {error && (
          <InlineError className="mb-4">
            {errorMessage(error)}
          </InlineError>
        )}

        {result && (
          <div className="mb-4 rounded-lg border border-green-900/50 bg-green-950/20 p-3.5">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle className="size-4 text-green-400" />
              <span className="text-sm font-medium text-green-300">Execution successful</span>
            </div>
            <pre className="text-xs text-fg-subtle overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result.output, null, 2)}</pre>
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
  const { can } = useCapabilities()
  const canExecute = can('tool:execute')
  const [executeTarget, setExecuteTarget] = useState(null)

  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(tenantId),
    queryFn: () => listTools(tenantId),
    enabled: Boolean(tenantId),
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
          <div className="min-w-0 flex-1">
            <PageHeader title="Tools"
          description="Platform-owned AI tools available for this tenant." />
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
                <p className="text-sm font-semibold text-fg">{tool.name}</p>
                <Badge
                  variant={
                    tool.risk_level === 'high' ? 'danger' :
                    tool.risk_level === 'medium' ? 'warning' : 'success'
                  }
                  size="sm"
                >
                  {tool.risk_level}
                </Badge>
              </div>
              <p className="text-[13px] text-fg-muted">{tool.description || 'No description'}</p>
              {tool.required_permissions && tool.required_permissions.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tool.required_permissions.map((perm) => (
                    <Badge key={perm} variant="neutral" size="sm">{perm}</Badge>
                  ))}
                </div>
              )}
              <div className="text-xs text-fg-muted">v{tool.version}</div>
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
