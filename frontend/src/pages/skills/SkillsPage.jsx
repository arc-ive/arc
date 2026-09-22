import { useState, useCallback, useRef } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Edit, Play, Plus, Trash2, Workflow, AlertTriangle, CheckCircle2, XCircle, ShieldAlert, Ban, Clock } from 'lucide-react'
import { queryKeys } from '../../api/queryKeys.js'
import { listSkills, getSkill, createSkill, updateSkill, deleteSkill, executeSkill } from '../../api/endpoints/skills.js'
import { useAuth } from '../../auth/useAuth.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { useTenant } from '../../tenant/useTenant.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { Spinner } from '../../components/ui/Spinner.jsx'
import { Dialog } from '../../components/ui/Dialog.jsx'
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

  const inputClass = "mt-1 block w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none font-mono"

  return (
    <Dialog open={open} onClose={handleClose}>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div className="w-full max-w-lg rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex size-10 items-center justify-center rounded-lg bg-indigo-950/50 border border-indigo-900/50">
              <Play className="size-5 text-indigo-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">Execute skill</h3>
              <p className="text-xs text-zinc-500">{skill.name}</p>
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
                  <p className="text-xs font-medium text-zinc-500">Steps</p>
                  {result.steps.map((step) => (
                    <div key={step.sequence} className="rounded border border-zinc-800 bg-zinc-950/50 p-2.5 text-xs">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-zinc-500">#{step.sequence + 1}</span>
                        <span className="text-zinc-300 font-mono">{step.tool_name}</span>
                        <Badge variant={step.status === 'success' ? 'green' : 'red'} size="sm">
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
                  <p className="text-xs text-zinc-500 mb-2">
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
                  <p className="text-xs text-zinc-500">No preconditions required for this skill.</p>
                </div>
              )}
              {declaredInputs.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-zinc-300 mb-2">
                    Skill inputs
                  </label>
                  <div className="space-y-2">
                    {declaredInputs.map((name) => (
                      <label key={name} className="block">
                        <span className="block text-xs text-zinc-400 mb-1">{name}</span>
                        <input
                          type="text"
                          value={inputValues[name] ?? ''}
                          onChange={(e) => setInputValue(name, e.target.value)}
                          disabled={mutation.isPending}
                          className="block w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-zinc-300">
                  Tool calls (JSON array)
                </label>
                <textarea
                  value={argsText}
                  onChange={(e) => setArgsText(e.target.value)}
                  className={inputClass}
                  rows={6}
                  placeholder='[{"tool_name": "check_service_health", "input": {}}]'
                  spellCheck={false}
                  disabled={mutation.isPending}
                />
                {jsonError && (
                  <p className="mt-1 text-xs text-red-400">{jsonError}</p>
                )}
              </div>
              {apiError && (
                <div className="rounded-lg border border-red-900/50 bg-red-950/20 px-3.5 py-3 text-[13px] text-red-300">
                  {apiError}
                </div>
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
    const payload = {
      name: form.name,
      purpose: form.purpose,
      version: form.version,
      inputs: form.inputs ? form.inputs.split(',').map((s) => s.trim()).filter(Boolean) : [],
      preconditions: form.preconditions ? form.preconditions.split('\n').filter(Boolean) : [],
      steps: form.steps ? form.steps.split('\n').filter(Boolean) : [],
      constraints: form.constraints ? form.constraints.split('\n').filter(Boolean) : [],
      allowed_tools: form.allowed_tools ? form.allowed_tools.split(',').map((s) => s.trim()).filter(Boolean) : [],
      approval_required: form.approval_required,
      expected_output: form.expected_output || null,
      failure_behavior: form.failure_behavior || null,
      provenance: form.provenance || null,
      risk: form.risk || null,
    }
    updateMutation.mutate(payload)
  }

  const inputClass = "mt-1 block w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"

  return (
    <Dialog open={open} onClose={handleClose}>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex size-10 items-center justify-center rounded-lg bg-indigo-950/50 border border-indigo-900/50">
              <Edit className="size-5 text-indigo-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-zinc-100">Edit skill</h3>
              <p className="text-xs text-zinc-500">{skill.name}</p>
            </div>
          </div>
          {error && (
            <div className="mb-4 rounded-lg border border-red-900/50 bg-red-950/20 px-3.5 py-3 text-[13px] text-red-300">
              {errorMessage(error)}
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-zinc-300">Name *</label>
              <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputClass} required />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Purpose *</label>
              <textarea value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} className={inputClass} rows={3} required />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-zinc-300">Version</label>
                <input type="text" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-300">Risk</label>
                <input type="text" value={form.risk} onChange={(e) => setForm({ ...form, risk: e.target.value })} className={inputClass} placeholder="e.g. low, medium, high" />
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-zinc-300">Provenance</label>
                <input type="text" value={form.provenance} onChange={(e) => setForm({ ...form, provenance: e.target.value })} className={inputClass} placeholder="e.g. HR department" />
              </div>
              <div className="flex items-center gap-2 pt-6">
                <input
                  type="checkbox"
                  id="edit_approval_required"
                  checked={form.approval_required}
                  onChange={(e) => setForm({ ...form, approval_required: e.target.checked })}
                  className="size-4 rounded border-zinc-700 bg-zinc-800"
                />
                <label htmlFor="edit_approval_required" className="text-sm text-zinc-300">Approval required</label>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Inputs (comma-separated)</label>
              <input type="text" value={form.inputs} onChange={(e) => setForm({ ...form, inputs: e.target.value })} className={inputClass} placeholder="e.g. username, department" />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Preconditions (one per line)</label>
              <textarea value={form.preconditions} onChange={(e) => setForm({ ...form, preconditions: e.target.value })} className={inputClass} rows={3} />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Steps (one per line)</label>
              <textarea value={form.steps} onChange={(e) => setForm({ ...form, steps: e.target.value })} className={inputClass} rows={4} />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Constraints (one per line)</label>
              <textarea value={form.constraints} onChange={(e) => setForm({ ...form, constraints: e.target.value })} className={inputClass} rows={2} />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Allowed Tools (comma-separated)</label>
              <input type="text" value={form.allowed_tools} onChange={(e) => setForm({ ...form, allowed_tools: e.target.value })} className={inputClass} />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-zinc-300">Expected Output</label>
                <input type="text" value={form.expected_output} onChange={(e) => setForm({ ...form, expected_output: e.target.value })} className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-300">Failure Behavior</label>
                <input type="text" value={form.failure_behavior} onChange={(e) => setForm({ ...form, failure_behavior: e.target.value })} className={inputClass} />
              </div>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="secondary" type="button" onClick={handleClose} disabled={updateMutation.isPending}>
                Cancel
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? 'Saving...' : 'Save changes'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </Dialog>
  )
}

function SkillList() {
  const queryClient = useQueryClient()
  const { tenantId } = useTenant()
  const { isDemo } = useAuth()
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
    enabled: !isDemo && Boolean(tenantId),
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
        <p className="text-sm text-zinc-500">
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
                    <p className="text-xs text-zinc-500 truncate">{skill.purpose || 'No description'}</p>
                  </div>
                </div>
              </Link>
              <div className="flex items-center gap-2 ml-4">
                <Badge variant={skill.status === 'active' ? 'green' : 'neutral'}>{skill.status}</Badge>
                <span className="text-xs text-zinc-600">v{skill.version}</span>
                {canExecute && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setExecuteTarget(skill)}
                    title="Execute skill"
                  >
                    <Play className="size-4 text-zinc-500" />
                  </Button>
                )}
                {canUpdate && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditTarget(skill)}
                    title="Edit skill"
                  >
                    <Edit className="size-4 text-zinc-500" />
                  </Button>
                )}
                {canDelete && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleteTarget(skill)}
                    disabled={deleteMutation.isPending}
                    title="Delete skill"
                  >
                    <Trash2 className="size-4 text-zinc-500" />
                  </Button>
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
  const { isDemo } = useAuth()
  const { can } = useCapabilities()
  const canUpdate = can('skill:update')
  const [editTarget, setEditTarget] = useState(null)
  const { data: skill, isLoading, error } = useQuery({
    queryKey: queryKeys.skill(tenantId, skillId),
    queryFn: () => getSkill(tenantId, skillId),
    enabled: !isDemo && Boolean(tenantId && skillId),
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
            <h3 className="text-lg font-semibold text-zinc-100">{skill.name}</h3>
            {skill.purpose && <p className="mt-1 text-sm text-zinc-500">{skill.purpose}</p>}
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
              <dt className="text-xs font-medium text-zinc-500">Status</dt>
              <dd className="mt-1">
                <Badge variant={skill.status === 'active' ? 'green' : 'neutral'}>{skill.status}</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-zinc-500">Version</dt>
              <dd className="mt-1 text-sm text-zinc-300">{skill.version}</dd>
            </div>
            {skill.provenance && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Provenance</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.provenance}</dd>
              </div>
            )}
            {skill.inputs && skill.inputs.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Inputs</dt>
                <dd className="mt-1 flex flex-wrap gap-2">
                  {skill.inputs.map((input, idx) => (
                    <Badge key={idx} variant="neutral">{input}</Badge>
                  ))}
                </dd>
              </div>
            )}
            {skill.preconditions && skill.preconditions.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Preconditions</dt>
                <dd className="mt-1 space-y-1">
                  {skill.preconditions.map((pre, idx) => (
                    <p key={idx} className="text-sm text-zinc-300">{pre}</p>
                  ))}
                </dd>
              </div>
            )}
            {skill.steps && skill.steps.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Steps</dt>
                <dd className="mt-1 space-y-1">
                  {skill.steps.map((step, idx) => (
                    <p key={idx} className="text-sm text-zinc-300">{idx + 1}. {step}</p>
                  ))}
                </dd>
              </div>
            )}
            {skill.constraints && skill.constraints.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Constraints</dt>
                <dd className="mt-1 space-y-1">
                  {skill.constraints.map((constraint, idx) => (
                    <p key={idx} className="text-sm text-zinc-300">{constraint}</p>
                  ))}
                </dd>
              </div>
            )}
            {skill.allowed_tools && skill.allowed_tools.length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Allowed Tools</dt>
                <dd className="mt-1 flex flex-wrap gap-2">
                  {skill.allowed_tools.map((tool) => (
                    <Badge key={tool} variant="indigo">{tool}</Badge>
                  ))}
                </dd>
              </div>
            )}
            <div>
              <dt className="text-xs font-medium text-zinc-500">Approval Required</dt>
              <dd className="mt-1 text-sm text-zinc-300">{skill.approval_required ? 'Yes' : 'No'}</dd>
            </div>
            {skill.risk && (
              <div>
                <dt className="text-xs font-medium text-zinc-500">Risk</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.risk}</dd>
              </div>
            )}
            {skill.expected_output && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Expected Output</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.expected_output}</dd>
              </div>
            )}
            {skill.failure_behavior && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-zinc-500">Failure Behavior</dt>
                <dd className="mt-1 text-sm text-zinc-300">{skill.failure_behavior}</dd>
              </div>
            )}
          </dl>
        </CardContent>
      </Card>
    </div>
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
    const payload = {
      name: form.name,
      purpose: form.purpose,
      version: form.version,
      inputs: form.inputs ? form.inputs.split(',').map((s) => s.trim()).filter(Boolean) : [],
      preconditions: form.preconditions ? form.preconditions.split('\n').filter(Boolean) : [],
      steps: form.steps ? form.steps.split('\n').filter(Boolean) : [],
      constraints: form.constraints ? form.constraints.split('\n').filter(Boolean) : [],
      allowed_tools: form.allowed_tools ? form.allowed_tools.split(',').map((s) => s.trim()).filter(Boolean) : [],
      approval_required: form.approval_required,
      expected_output: form.expected_output || undefined,
      failure_behavior: form.failure_behavior || undefined,
      provenance: form.provenance || undefined,
    }
    createMutation.mutate(payload)
  }

  const inputClass = "mt-1 block w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"

  return (
    <Card>
      <CardHeader title="Create Skill" description="Define a new skill for this tenant." />
      <CardContent>
        {error && (
          <div className="mb-4 rounded-lg border border-red-900/50 bg-red-950/20 px-3.5 py-3 text-[13px] text-red-300">
            {errorMessage(error)}
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-300">Name *</label>
            <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputClass} required />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300">Purpose *</label>
            <textarea value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} className={inputClass} rows={3} required />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-zinc-300">Version</label>
              <input type="text" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} className={inputClass} />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Provenance</label>
              <input type="text" value={form.provenance} onChange={(e) => setForm({ ...form, provenance: e.target.value })} className={inputClass} placeholder="e.g. HR department" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300">Inputs (comma-separated)</label>
            <input type="text" value={form.inputs} onChange={(e) => setForm({ ...form, inputs: e.target.value })} className={inputClass} placeholder="e.g. username, department" />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300">Preconditions (one per line)</label>
            <textarea value={form.preconditions} onChange={(e) => setForm({ ...form, preconditions: e.target.value })} className={inputClass} rows={3} placeholder="e.g. User must be authenticated" />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300">Steps (one per line)</label>
            <textarea value={form.steps} onChange={(e) => setForm({ ...form, steps: e.target.value })} className={inputClass} rows={4} placeholder="e.g. 1. Verify identity&#10;2. Check permissions&#10;3. Execute action" />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300">Constraints (one per line)</label>
            <textarea value={form.constraints} onChange={(e) => setForm({ ...form, constraints: e.target.value })} className={inputClass} rows={2} placeholder="e.g. Max 5 retries" />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-300">Allowed Tools (comma-separated)</label>
            <input type="text" value={form.allowed_tools} onChange={(e) => setForm({ ...form, allowed_tools: e.target.value })} className={inputClass} placeholder="e.g. check_service_health" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-zinc-300">Expected Output</label>
              <input type="text" value={form.expected_output} onChange={(e) => setForm({ ...form, expected_output: e.target.value })} className={inputClass} />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-300">Failure Behavior</label>
              <input type="text" value={form.failure_behavior} onChange={(e) => setForm({ ...form, failure_behavior: e.target.value })} className={inputClass} placeholder="e.g. escalate to ops" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="approval_required"
              checked={form.approval_required}
              onChange={(e) => setForm({ ...form, approval_required: e.target.checked })}
              className="size-4 rounded border-zinc-700 bg-zinc-800"
            />
            <label htmlFor="approval_required" className="text-sm text-zinc-300">Approval required before execution</label>
          </div>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Creating...' : 'Create Skill'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

export function SkillsPage({ view = 'list' }) {
  const { tenantId, skillId } = useParams()
  const tenantPrefix = `/app/t/${encodeURIComponent(tenantId)}`

  const viewCopy = {
    list: {
      title: 'Skills',
      description: 'Structured, reusable workflows that convert company procedures into capabilities Unified Intelligence can apply.',
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
            className="mb-4 inline-flex items-center gap-1.5 rounded text-[13px] text-zinc-500 transition-colors duration-150 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
          >
            <ArrowLeft className="size-3.5" />
            Back to Skills
          </Link>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Workflow className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">{viewCopy.title}</h1>
            <p className="mt-1 text-sm text-zinc-500">{viewCopy.description}</p>
          </div>
        </div>
      </section>

      {view === 'list' && <SkillList />}
      {view === 'new' && <SkillForm />}
      {view === 'detail' && <SkillDetail skillId={skillId} />}
    </div>
  )
}
