import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FilePlus2, Info } from 'lucide-react'
import { createKnowledge, KNOWLEDGE_SOURCES } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { sourceLabels } from '../../lib/sources.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardHeader, CardContent } from '../../components/ui/Card.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Select } from '../../components/ui/Select.jsx'

export function NewKnowledgePage() {
  const { tenantId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [form, setForm] = useState({
    source: 'policy',
    provenance: '',
    content: '',
    version: '1',
  })
  const [errors, setErrors] = useState({})

  const mutation = useMutation({
    mutationFn: () =>
      createKnowledge(tenantId, {
        source: form.source,
        provenance: form.provenance.trim(),
        content: form.content,
        version: Number(form.version) || 1,
      }),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge(tenantId) })
      navigate(`/app/t/${encodeURIComponent(tenantId)}/knowledge/${doc.id}`)
    },
    onError: (err) => setErrors({ api: errorMessage(err) }),
  })

  const validate = () => {
    const next = {}
    if (!form.provenance.trim()) {
      next.provenance = 'Source is required.'
    }
    if (!form.content.trim()) {
      next.content = 'Content is required.'
    }
    if (form.version && (Number(form.version) < 1 || Number.isNaN(Number(form.version)))) {
      next.version = 'Version must be an integer >= 1.'
    }
    return next
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    const next = validate()
    setErrors(next)
    if (Object.keys(next).length === 0) {
      mutation.mutate()
    }
  }

  const backTo = `/app/t/${encodeURIComponent(tenantId)}/knowledge`

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <section>
        <Link
          to={backTo}
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <ArrowLeft className="size-3.5" />
          Back to Company Brain
        </Link>
        <PageHeader title="New knowledge document"
          description="Content is PII-sanitized by the backend before it is stored." />
      </section>

      <Card>
        <CardHeader
          title="Document details"
          description="Provide a source, provenance, and the knowledge content."
        />
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <Select
                label="Document type"
                required
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                disabled={mutation.isPending}
              >
                {KNOWLEDGE_SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {sourceLabels[s]}
                  </option>
                ))}
              </Select>
              <Input
                label="Version"
                type="number"
                min="1"
                step="1"
                value={form.version}
                onChange={(e) => setForm({ ...form, version: e.target.value })}
                error={errors.version}
                disabled={mutation.isPending}
                hint="Defaults to 1."
              />
            </div>

            <Input
              label="Source"
              required
              placeholder="e.g. SOC-2 policy revision, incident INC-1234 postmortem…"
              value={form.provenance}
              onChange={(e) => setForm({ ...form, provenance: e.target.value })}
              error={errors.provenance}
              disabled={mutation.isPending}
              hint="Where this knowledge comes from. Shown as the document's identity."
            />

            <Textarea
              label="Content"
              required
              rows={12}
              placeholder="The knowledge itself — the body of the policy, procedure, or note…"
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              error={errors.content}
              disabled={mutation.isPending}
              textareaClassName="font-mono text-[13px]"
            />

            <div className="flex items-start gap-2.5 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3.5 py-3">
              <Info className="mt-0.5 size-4 shrink-0 text-fg-muted" />
              <p className="text-xs leading-relaxed text-fg-muted">
                Submitted documents are validated by the backend:{' '}
                <span className="font-mono">source</span> must be one of the
                six supported sources, <span className="font-mono">provenance</span>{' '}
                and <span className="font-mono">content</span> must be non-empty,
                and <span className="font-mono">version</span> must be ≥ 1.
              </p>
            </div>

            {errors.api && (
              <InlineError>
                {errors.api}
              </InlineError>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-zinc-800/70 pt-4">
              <Button
                variant="secondary"
                onClick={() => navigate(backTo)}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                isLoading={mutation.isPending}
                loadingText="Creating…"
              >
                <FilePlus2 className="size-4" />
                Create document
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}