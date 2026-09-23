import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Play, CheckCircle } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import { listTools, executeTool } from '../../api/endpoints/tools.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { toolLabel } from '../../lib/approvals.js'
import { Button } from '../../components/ui/Button.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
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
          <div className="mb-4 rounded-lg border border-success/30 bg-success/10 p-3.5">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle className="size-4 text-success" />
              <span className="text-sm font-medium text-success">Execution successful</span>
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

const RISK_TONE = { high: 'danger', medium: 'warning', low: 'success' }

export function ToolsPage() {
  useDocumentTitle('Tools')
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
    <div className="flex flex-col">
      {/* Tools are the actions Arc can take. A person comes here to see
          what is available and, occasionally, to run one by hand — so the
          composition is a capability list with its inputs visible, not a
          grid of identical cards. */}
      <header className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <h1 className="type-display-lg text-fg">Tools</h1>
          {!isLoading && tools?.length > 0 && (
            <p className="mt-2 measure text-[14px] text-fg-muted">
              {tools.length} {tools.length === 1 ? 'action' : 'actions'} Arc can
              take. Registered by the platform — they cannot be changed here.
            </p>
          )}
        </div>
      </header>

      <ToolExecuteDialog
        tool={executeTarget}
        open={Boolean(executeTarget)}
        onClose={() => setExecuteTarget(null)}
      />

      {isLoading && (
        <div className="mt-8 flex flex-col gap-4 border-t border-line pt-6">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
      )}

      {failed && (
        <div className="mt-8">
          <ErrorState
            error={error}
            message={error ? undefined : STALLED_MESSAGE}
            onRetry={() => toolsQuery.refetch()}
          />
        </div>
      )}

      {!isLoading && !failed && (!tools || tools.length === 0) && (
        <p className="measure mt-8 border-t border-line pt-6 type-prose text-fg-subtle">
          No tools are registered for this workspace yet.
        </p>
      )}

      {!isLoading && !failed && tools?.length > 0 && (
        <ul className="mt-8 border-t border-line">
          {tools.map((tool) => {
            const inputs = Object.keys(tool.input_schema?.properties ?? {})
            const required = new Set(tool.input_schema?.required ?? [])
            return (
              <li
                key={tool.name}
                className="grid grid-cols-1 gap-x-10 gap-y-4 border-b border-line py-6 lg:grid-cols-[minmax(0,1fr)_16rem]"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    {/* The registry key was the heading. It is the name a
                        person would say, set in the serif, with the key
                        kept below where it is useful for writing a call. */}
                    <h2 className="type-display text-[1.25rem] leading-snug text-fg">
                      {toolLabel(tool.name)}
                    </h2>
                    <Badge variant={RISK_TONE[tool.risk_level] ?? 'neutral'} size="sm">
                      {tool.risk_level} risk
                    </Badge>
                  </div>
                  <p className="measure mt-1.5 text-[14px] leading-relaxed text-fg-subtle">
                    {tool.description || 'No description.'}
                  </p>
                  <p className="type-data mt-2 text-fg-muted">
                    {tool.name} · v{tool.version}
                  </p>
                </div>

                <div className="flex flex-col items-start gap-4 lg:items-end">
                  {/* What the tool needs, which is the thing a person
                      actually has to know before running one. The
                      `tool:execute` permission chip that used to sit here
                      told them nothing they could act on — if they may not
                      run it, the button is simply absent. */}
                  {inputs.length > 0 && (
                    <dl className="w-full lg:text-right">
                      <dt className="type-label text-fg-muted">Takes</dt>
                      <dd className="type-data mt-1 text-fg-subtle">
                        {inputs
                          .map((k) => (required.has(k) ? `${k}*` : k))
                          .join(', ')}
                      </dd>
                    </dl>
                  )}
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
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
