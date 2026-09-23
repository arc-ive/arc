import { useState, useCallback, useRef } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Edit, Play, Plus, Trash2, Workflow, AlertTriangle, CheckCircle2, XCircle, ShieldAlert, Ban, Clock } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import { listSkills, getSkill, createSkill, updateSkill, deleteSkill, executeSkill } from '../../api/endpoints/skills.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardContent } from '../../components/ui/Card.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
import { IconButton } from '../../components/ui/IconButton.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Checkbox } from '../../components/ui/Checkbox.jsx'
import { RISK_LEVELS, riskLabel, riskTone } from '../../lib/skills.js'
import { errorMessage } from '../../api/errors.js'

function DeleteConfirmDialog({ open, onConfirm, onCancel, skillName, isPending, error }) {
  // The confirmation is driven entirely by Dialog's own `open`/`onClose`
  // contract. Passing no props left Dialog's `open` undefined, so it returned
  // null and the confirmation could never appear — the delete button set state
  // and nothing happened. Dialog also supplies the overlay, focus management,
  // Escape handling and the labelled heading, so none of that is re-created
  // here.
  return (
    <Dialog
      open={open}
      onClose={isPending ? () => {} : onCancel}
      title="Delete skill"
      description="This action cannot be undone."
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={isPending}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={isPending}>
            {isPending ? 'Deleting…' : 'Delete'}
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-red-900/50 bg-red-950/50">
          <AlertTriangle className="size-5 text-red-400" />
        </div>
        <p className="text-sm text-zinc-400">
          Are you sure you want to delete{' '}
          <span className="font-medium text-zinc-200">{skillName}</span>?
        </p>
      </div>
      {error && (
        <p className="mt-4 text-sm text-red-400" role="alert">
          {errorMessage(error)}
        </p>
      )}
    </Dialog>
  )
}

const STATUS_CONFIG = {
  succeeded: { icon: CheckCircle2, label: 'Succeeded', variant: 'green' },
  failed: { icon: XCircle, label: 'Failed', variant: 'red' },
  precondition_failed: { icon: ShieldAlert, label: 'Precondition failed', variant: 'amber' },
  approval_required: { icon: Clock, label: 'Approval required', variant: 'amber' },
  denied: { icon: Ban, label: 'Denied', variant: 'red' },
}

function ExecuteSkillDialog({ open, onClose, skill }) {
  const queryClient = useQueryClient()
  const { tenantId } = useTenant()
  const [argsText, setArgsText] = useState('[]')
  const [jsonError, setJsonError] = useState(null)
  const [apiError, setApiError] = useState(null)
  const [result, setResult] = useState(null)
  const [selectedPreconditions, setSelectedPreconditions] = useState([])
  const [inputValues, setInputValues] = useState({})

  const mutation = useMutation({
    mutationFn: () => {
      const tool_calls = JSON.parse(argsText)
      const body = { tool_calls }
      if (selectedPreconditions.length > 0) {
        body.satisfied_preconditions = selectedPreconditions
      }
      const skill_inputs = Object.fromEntries(
        Object.entries(inputValues).filter(([, value]) => value !== '')
      )
      if (Object.keys(skill_inputs).length > 0) {
        body.skill_inputs = skill_inputs
      }
      return executeSkill(tenantId, skill.id, body)
    },
    onSuccess: (data) => {
      setResult(data)
      queryClient.invalidateQueries({ queryKey: queryKeys.skills(tenantId) })
    },
    onError: (err) => setApiError(errorMessage(err)),
  })

  const handleClose = useCallback(() => {
    if (mutation.isPending) return
    onClose()
    setArgsText('[]')
    setJsonError(null)
    setApiError(null)
    setResult(null)
    setSelectedPreconditions([])
    setInputValues({})
  }, [mutation.isPending, onClose])

  if (!open || !skill) return null

  const handleSubmit = () => {
    setJsonError(null)
    setApiError(null)
    try {
      const parsed = JSON.parse(argsText)
      if (!Array.isArray(parsed)) {
        setJsonError('Tool-call arguments must be a JSON array')
        return
      }
      mutation.mutate()
    } catch {
      setJsonError('Invalid JSON — please check your input')
    }
  }

  const hasPreconditions = skill.preconditions && skill.preconditions.length > 0
  const declaredInputs = skill.inputs && skill.inputs.length > 0 ? skill.inputs : []

  const setInputValue = (name, value) => {
    setInputValues((prev) => ({ ...prev, [name]: value }))
  }

  const togglePrecondition = (pre) => {
    setSelectedPreconditions((prev) =>
      prev.includes(pre) ? prev.filter((p) => p !== pre) : [...prev, pre],
    )
  }

  return (
    <Dialog open={open} onClose={handleClose}>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div className="w-full max-w-lg rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex size-10 items-center justify-center rounded-lg bg-indigo-950/50 border border-indigo-900/50">
              <Play className="size-5 text-indigo-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">Execute skill</h2>
              <p className="text-xs text-fg-muted">{skill.name}</p>
            </div>
          </div>

          {result ? (
            <div className="space-y-3 mb-6">
              <div className="flex items-center gap-2">
                {(() => {
                  const cfg = STATUS_CONFIG[result.status]
                  const Icon = cfg?.icon ?? CheckCircle2
                  return (
                    <>
                      <Badge variant={cfg?.variant ?? 'neutral'}>
                        <Icon className="size-3" />
                        {cfg?.label ?? result.status}
                      </Badge>
                    </>
                  )
                })()}
              </div>
              {result.error_kind && (
                <p className="text-xs text-zinc-400">
                  Error: <span className="text-zinc-300">{result.error_kind}</span>
                </p>
              )}
              {result.steps && result.steps.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-fg-muted">Steps</p>
                  {result.steps.map((step) => (
                    <div key={step.sequence} className="rounded border border-zinc-800 bg-zinc-950/50 p-2.5 text-xs">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-fg-muted">#{step.sequence + 1}</span>
                        <span className="text-zinc-300 font-mono">{step.tool_name}</span>
                        <Badge variant={step.status === 'success' ? 'success' : 'danger'} size="sm">
                          {step.status}
                        </Badge>
                      </div>
                      {step.output && (
                        <pre className="mt-1 whitespace-pre-wrap text-zinc-400 overflow-x-auto">
                          {JSON.stringify(step.output, null, 2)}
                        </pre>
                      )}
                      {step.error_kind && (
                        <p className="mt-1 text-red-400">{step.error_kind}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4 mb-6">
              {hasPreconditions && (
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Preconditions
                  </label>
                  <p className="text-xs text-fg-muted mb-2">
                    Confirm that each precondition is satisfied before executing.
                  </p>
                  <div className="space-y-2">
                    {skill.preconditions.map((pre, idx) => (
                      <label key={idx} className="flex items-start gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedPreconditions.includes(pre)}
                          onChange={() => togglePrecondition(pre)}
                          disabled={mutation.isPending}
                          className="mt-0.5 size-4 rounded border-zinc-600 bg-zinc-800 text-indigo-500 focus:ring-indigo-500/40"
                        />
                        <span className="text-sm text-zinc-300">{pre}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
              {!hasPreconditions && (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3.5 py-2.5">
                  <p className="text-xs text-fg-muted">No preconditions required for this skill.</p>
                </div>
              )}
              {declaredInputs.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Skill inputs
                  </label>
                  <div className="space-y-2">
                    {declaredInputs.map((name) => (
                      <Input
                        key={name}
                        label={name}
                        value={inputValues[name] ?? ''}
                        onChange={(e) => setInputValue(name, e.target.value)}
                        disabled={mutation.isPending}
                      />
                    ))}
                  </div>
                </div>
              )}
              <Textarea
                label="Tool calls (JSON array)"
                value={argsText}
                onChange={(e) => setArgsText(e.target.value)}
                textareaClassName="font-mono"
                rows={6}
                placeholder='[{"tool_name": "check_service_health", "input": {}}]'
                spellCheck={false}
                disabled={mutation.isPending}
                error={jsonError || undefined}
              />
              {apiError && (
                <InlineError>
                  {apiError}
                </InlineError>
              )}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={handleClose} disabled={mutation.isPending}>
              {result ? 'Close' : 'Cancel'}
            </Button>
            {!result && (
              <Button onClick={handleSubmit} disabled={mutation.isPending}>
                {mutation.isPending ? 'Executing...' : 'Execute'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </Dialog>
  )
}

function EditSkillDialog({ open, skill, onClose }) {
  const queryClient = useQueryClient()
  const { tenantId } = useTenant()
  const [form, setForm] = useState({
    name: '',
    purpose: '',
    version: '',
    inputs: '',
    preconditions: '',
    steps: '',
    constraints: '',
    allowed_tools: '',
    approval_required: false,
    expected_output: '',
    failure_behavior: '',
    provenance: '',
    risk: '',
  })
  const [error, setError] = useState(null)

  const updateMutation = useMutation({
    mutationFn: (data) => updateSkill(tenantId, skill.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills(tenantId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.skill(tenantId, skill.id) })
      onClose()
    },
    onError: (err) => setError(err),
  })

  const prevSkillIdRef = useRef(null)
  if (prevSkillIdRef.current !== skill?.id) {
    prevSkillIdRef.current = skill?.id ?? null
    if (skill) {
      setForm({
        name: skill.name || '',
        purpose: skill.purpose || '',
        version: skill.version || '1',
        inputs: (skill.inputs || []).join(', '),
        preconditions: (skill.preconditions || []).join('\n'),
        steps: (skill.steps || []).join('\n'),
        constraints: (skill.constraints || []).join('\n'),
        allowed_tools: (skill.allowed_tools || []).join(', '),
        approval_required: skill.approval_required || false,
        expected_output: skill.expected_output || '',
        failure_behavior: skill.failure_behavior || '',
        provenance: skill.provenance || '',
        risk: skill.risk || '',
      })
      setError(null)
    }
  }

  const handleClose = useCallback(() => {
    if (updateMutation.isPending) return
    onClose()
  }, [updateMutation.isPending, onClose])

  if (!open || !skill) return null

  const handleSubmit = (e) => {
    e.preventDefault()
    setError(null)
    updateMutation.mutate({ ...skillPayload(form), risk: form.risk || null })
  }

  return (
    <Dialog open={open} onClose={handleClose}>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
        <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-line bg-panel shadow-xl">
          <div className="border-b border-line px-6 py-4">
            <h2 className="text-sm font-semibold text-fg">Edit skill</h2>
            <p className="mt-0.5 text-xs text-fg-muted">{skill.name}</p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {error && (
              <InlineError className="mb-4">
                {errorMessage(error)}
              </InlineError>
            )}
            <form id="edit-skill-form" onSubmit={handleSubmit}>
              <SkillFields form={form} setForm={setForm} />
            </form>
          </div>
          <div className="flex justify-end gap-3 border-t border-line px-6 py-4">
            <Button variant="secondary" type="button" onClick={handleClose} disabled={updateMutation.isPending}>
              Cancel
            </Button>
            <Button form="edit-skill-form" type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving...' : 'Save changes'}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}

function SkillList() {
  const queryClient = useQueryClient()
  const { tenantId } = useTenant()
  const { can } = useCapabilities()
  const canCreate = can('skill:create')
  const canUpdate = can('skill:update')
  const canDelete = can('skill:delete')
  const canExecute = can('skill:execute')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [editTarget, setEditTarget] = useState(null)
  const [executeTarget, setExecuteTarget] = useState(null)

  const { data: skills, isLoading, error } = useQuery({
    queryKey: queryKeys.skills(tenantId),
    queryFn: () => listSkills(tenantId),
    enabled: Boolean(tenantId),
  })

  const deleteMutation = useMutation({
    mutationFn: ({ skillId }) => deleteSkill(tenantId, skillId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills(tenantId) })
      setDeleteTarget(null)
    },
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorState error={error} />

  if (!skills || skills.length === 0) {
    return (
      <EmptyState
        icon={Workflow}
        title="No skills yet"
        description="Create your first skill to define a reusable workflow."
        action={
          canCreate && (
            <Link to="new">
              <Button>
                <Plus className="size-4" />
                New Skill
              </Button>
            </Link>
          )
        }
      />
    )
  }

  return (
    <div className="space-y-3">
      <EditSkillDialog
        open={Boolean(editTarget)}
        skill={editTarget}
        onClose={() => setEditTarget(null)}
      />
      <DeleteConfirmDialog
        open={Boolean(deleteTarget)}
        skillName={deleteTarget?.name}
        isPending={deleteMutation.isPending}
        error={deleteMutation.error}
        onConfirm={() => deleteTarget && deleteMutation.mutate({ skillId: deleteTarget.id })}
        onCancel={() => {
          // Reset so a failure from a previous attempt is not shown the next
          // time the dialog opens.
          deleteMutation.reset()
          setDeleteTarget(null)
        }}
      />
      <ExecuteSkillDialog
        open={Boolean(executeTarget)}
        skill={executeTarget}
        onClose={() => setExecuteTarget(null)}
      />
      <div className="flex items-center justify-between">
        <p className="text-sm text-fg-muted">
          {skills.length} skill{skills.length !== 1 ? 's' : ''}
        </p>
        {canCreate && (
          <Link to="new">
            <Button size="sm">
              <Plus className="size-4" />
              New Skill
            </Button>
          </Link>
        )}
      </div>
      <div className="grid gap-3">
        {skills.map((skill) => (
          <Card key={skill.id} className="transition-colors hover:border-zinc-700">
            <div className="flex items-center justify-between p-4">
              <Link to={`${skill.id}`} className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <div className="flex size-9 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60">
                    <Workflow className="size-4 text-zinc-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-zinc-100 truncate">{skill.name}</p>
                    <p className="text-xs text-fg-muted truncate">{skill.purpose || 'No description'}</p>
                  </div>
                </div>
              </Link>
              <div className="flex items-center gap-2 ml-4">
                <Badge variant={skill.status === 'active' ? 'success' : 'neutral'}>{skill.status}</Badge>
                <span className="text-xs text-fg-muted">v{skill.version}</span>
                {canExecute && (
                  <IconButton
                    size="sm"
                    onClick={() => setExecuteTarget(skill)}
                    label={`Execute ${skill.name}`}
                  >
                    <Play className="size-4" />
                  </IconButton>
                )}
                {canUpdate && (
                  <IconButton
                    size="sm"
                    onClick={() => setEditTarget(skill)}
                    label={`Edit ${skill.name}`}
                  >
                    <Edit className="size-4" />
                  </IconButton>
                )}
                {canDelete && (
                  <IconButton
                    variant="danger"
                    size="sm"
                    onClick={() => setDeleteTarget(skill)}
                    disabled={deleteMutation.isPending}
                    label={`Delete ${skill.name}`}
                  >
                    <Trash2 className="size-4" />
                  </IconButton>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

function SkillDetail({ skillId }) {
  const { tenantId } = useTenant()
  const { can } = useCapabilities()
  const canUpdate = can('skill:update')
  const [editTarget, setEditTarget] = useState(null)
  const { data: skill, isLoading, error } = useQuery({
    queryKey: queryKeys.skill(tenantId, skillId),
    queryFn: () => getSkill(tenantId, skillId),
    enabled: Boolean(tenantId && skillId),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorState error={error} />
  if (!skill) return <EmptyState title="Skill not found" />

  return (
    <div className="space-y-4">
      <EditSkillDialog
        open={Boolean(editTarget)}
        skill={editTarget}
        onClose={() => setEditTarget(null)}
      />
      <Card>
        <div className="flex items-center justify-between px-6 pt-6">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">{skill.name}</h2>
            {skill.purpose && <p className="mt-1 text-sm text-fg-muted">{skill.purpose}</p>}
          </div>
          {canUpdate && (
            <Button variant="secondary" size="sm" onClick={() => setEditTarget(skill)}>
              <Edit className="size-4" />
              Edit
            </Button>
          )}
        </div>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium text-fg-muted">Status</dt>
              <dd className="mt-1">
                <Badge variant={skill.status === 'active' ? 'success' : 'neutral'}>{skill.status}</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-fg-muted">Version</dt>
              <dd className="mt-1 text-sm text-zinc-300">{skill.version}</dd>
            </div>
            {skill.provenance && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Provenance</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.provenance}</dd>
              </div>
            )}
            {skill.inputs && skill.inputs.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Inputs</dt>
                <dd className="mt-1 flex flex-wrap gap-2">
                  {skill.inputs.map((input, idx) => (
                    <Badge key={idx} variant="neutral">{input}</Badge>
                  ))}
                </dd>
              </div>
            )}
            {skill.preconditions && skill.preconditions.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Preconditions</dt>
                <dd className="mt-1 space-y-1">
                  {skill.preconditions.map((pre, idx) => (
                    <p key={idx} className="text-sm text-zinc-300">{pre}</p>
                  ))}
                </dd>
              </div>
            )}
            {skill.steps && skill.steps.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Steps</dt>
                <dd className="mt-1 space-y-1">
                  {skill.steps.map((step, idx) => (
                    <p key={idx} className="text-sm text-zinc-300">{idx + 1}. {step}</p>
                  ))}
                </dd>
              </div>
            )}
            {skill.constraints && skill.constraints.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Constraints</dt>
                <dd className="mt-1 space-y-1">
                  {skill.constraints.map((constraint, idx) => (
                    <p key={idx} className="text-sm text-zinc-300">{constraint}</p>
                  ))}
                </dd>
              </div>
            )}
            {skill.allowed_tools && skill.allowed_tools.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Allowed Tools</dt>
                <dd className="mt-1 flex flex-wrap gap-2">
                  {skill.allowed_tools.map((tool) => (
                    <Badge key={tool} variant="accent">{tool}</Badge>
                  ))}
                </dd>
              </div>
            )}
            <div>
              <dt className="text-xs font-medium text-fg-muted">Approval Required</dt>
              <dd className="mt-1 text-sm text-zinc-300">{skill.approval_required ? 'Yes' : 'No'}</dd>
            </div>
            {skill.risk && (
              <div>
                <dt className="text-xs font-medium text-fg-muted">Risk</dt>
                <dd className="mt-1">
                  <Badge variant={riskTone(skill.risk)} size="sm">
                    {riskLabel(skill.risk)}
                  </Badge>
                </dd>
              </div>
            )}
            {skill.expected_output && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Expected Output</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.expected_output}</dd>
              </div>
            )}
            {skill.failure_behavior && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-fg-muted">Failure Behavior</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.failure_behavior}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * The skill form, grouped.
 *
 * Thirteen fields had been running as one flat list of look-alike inputs,
 * every label weighted the same, so nothing said which of them decide
 * whether the skill can run. They are grouped here by what they do:
 * what the skill is, what it does, and the policy that gates it.
 */
function SkillFields({ form, setForm, includeRisk = true }) {
  const set = (patch) => setForm({ ...form, ...patch })

  return (
    <div className="flex flex-col gap-6">
      <FormSection title="Identity">
        <Input
          label="Name"
          required
          value={form.name}
          onChange={(e) => set({ name: e.target.value })}
          className="sm:col-span-2"
        />
        <Textarea
          label="Purpose"
          required
          rows={3}
          value={form.purpose}
          onChange={(e) => set({ purpose: e.target.value })}
          className="sm:col-span-2"
          hint="What this skill is for, in a sentence."
        />
        <Input
          label="Version"
          value={form.version}
          onChange={(e) => set({ version: e.target.value })}
        />
        <Input
          label="Provenance"
          value={form.provenance}
          onChange={(e) => set({ provenance: e.target.value })}
          placeholder="e.g. HR department"
          hint="Who owns this skill."
        />
      </FormSection>

      <FormSection title="Procedure">
        <Input
          label="Inputs"
          value={form.inputs}
          onChange={(e) => set({ inputs: e.target.value })}
          placeholder="e.g. username, department"
          hint="Comma-separated."
          className="sm:col-span-2"
        />
        <Textarea
          label="Steps"
          rows={4}
          value={form.steps}
          onChange={(e) => set({ steps: e.target.value })}
          placeholder={'Verify identity\nCheck permissions\nExecute action'}
          hint="One per line."
          className="sm:col-span-2"
        />
        <Textarea
          label="Preconditions"
          rows={3}
          value={form.preconditions}
          onChange={(e) => set({ preconditions: e.target.value })}
          placeholder="e.g. User must be authenticated"
          hint="One per line. Checked before the skill runs."
        />
        <Textarea
          label="Constraints"
          rows={3}
          value={form.constraints}
          onChange={(e) => set({ constraints: e.target.value })}
          placeholder="e.g. Max 5 retries"
          hint="One per line."
        />
        <Input
          label="Allowed tools"
          value={form.allowed_tools}
          onChange={(e) => set({ allowed_tools: e.target.value })}
          placeholder="e.g. check_service_health"
          hint="Comma-separated. Tools outside this list are refused."
          className="sm:col-span-2"
        />
        <Input
          label="Expected output"
          value={form.expected_output}
          onChange={(e) => set({ expected_output: e.target.value })}
        />
        <Input
          label="Failure behaviour"
          value={form.failure_behavior}
          onChange={(e) => set({ failure_behavior: e.target.value })}
          placeholder="e.g. escalate to ops"
        />
      </FormSection>

      <FormSection title="Execution policy">
        {includeRisk && (
          <Select
            label="Risk"
            value={form.risk}
            onChange={(e) => set({ risk: e.target.value })}
            hint="Feeds the execution policy. It does not create an approval."
          >
            <option value="">Not classified</option>
            {RISK_LEVELS.map((level) => (
              <option key={level.value} value={level.value}>
                {level.label}
              </option>
            ))}
          </Select>
        )}
        <Checkbox
          label="Approval required before execution"
          checked={form.approval_required}
          onChange={(e) => set({ approval_required: e.target.checked })}
          hint="A separate control from risk. This holds the skill until someone approves it."
          className={includeRisk ? 'pt-6' : 'sm:col-span-2'}
        />
      </FormSection>
    </div>
  )
}

function FormSection({ title, children }) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-3 w-full border-b border-line pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-muted">
        {title}
      </legend>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </fieldset>
  )
}

function SkillForm() {
  const queryClient = useQueryClient()
  const { tenantId } = useTenant()
  const [form, setForm] = useState({
    name: '',
    purpose: '',
    version: '1',
    inputs: '',
    preconditions: '',
    steps: '',
    constraints: '',
    allowed_tools: '',
    approval_required: false,
    expected_output: '',
    failure_behavior: '',
    provenance: '',
    risk: '',
  })
  const [error, setError] = useState(null)

  const createMutation = useMutation({
    mutationFn: (skill) => createSkill(tenantId, skill),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills(tenantId) })
    },
    onError: (err) => setError(err),
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    setError(null)
    createMutation.mutate({ ...skillPayload(form), risk: form.risk || undefined })
  }

  return (
    <Card>
      <CardContent className="pt-6">
        {error && (
          <InlineError className="mb-4">
            {errorMessage(error)}
          </InlineError>
        )}
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <SkillFields form={form} setForm={setForm} />
          <div>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? 'Creating…' : 'Create skill'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

/**
 * The list/newline fields the API expects as arrays.
 *
 * Both forms had their own copy of this, which is how the create form came
 * to omit `risk` entirely — a skill could only be classified after it
 * already existed.
 */
function skillPayload(form) {
  const list = (value, sep) =>
    value ? value.split(sep).map((s) => s.trim()).filter(Boolean) : []

  return {
    name: form.name,
    purpose: form.purpose,
    version: form.version,
    inputs: list(form.inputs, ','),
    preconditions: list(form.preconditions, '\n'),
    steps: list(form.steps, '\n'),
    constraints: list(form.constraints, '\n'),
    allowed_tools: list(form.allowed_tools, ','),
    approval_required: form.approval_required,
    expected_output: form.expected_output || null,
    failure_behavior: form.failure_behavior || null,
    provenance: form.provenance || null,
  }
}

export function SkillsPage({ view = 'list' }) {
  const { tenantId, skillId } = useParams()
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  const viewCopy = {
    list: {
      title: 'Skills',
      description: 'Structured, reusable workflows that turn company procedures into capabilities Arc can apply.',
    },
    new: {
      title: 'New skill',
      description: 'Author a new skill definition for this tenant.',
    },
    detail: {
      title: 'Skill details',
      description: 'Inspect a skill definition for this tenant.',
    },
  }[view]

  return (
    <div className="flex flex-col gap-6">
      <section>
        {view !== 'list' && (
          <Link
            to={`${tenantPrefix}/skills`}
            className="mb-4 inline-flex items-center gap-1.5 rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          >
            <ArrowLeft className="size-3.5" />
            Back to Skills
          </Link>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <PageHeader title={viewCopy.title}
          description={viewCopy.description} />
          </div>
        </div>
      </section>

      {view === 'list' && <SkillList />}
      {view === 'new' && <SkillForm />}
      {view === 'detail' && <SkillDetail skillId={skillId} />}
    </div>
  )
}
