import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { createKnowledge, KNOWLEDGE_SOURCES } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { sourceLabels } from '../../lib/sources.js'
import { Button } from '../../components/ui/Button.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'

/**
 * Writing something into the Company Brain.
 *
 * Recomposed around the one field that matters. The content IS the
 * document; type, version and provenance are how it gets filed. The
 * previous version gave all four the same weight inside a card whose
 * header repeated the page's own title, and closed with a bordered note
 * restating validation rules the fields already enforce — three pieces of
 * chrome between the writer and the writing.
 *
 * So: the metadata sits in one quiet band, the content gets the page, and
 * the rules appear as field hints where a rule can actually be acted on.
 */
export function NewKnowledgePage() {
  useDocumentTitle('New document')
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
  const words = form.content.trim() ? form.content.trim().split(/\s+/).length : 0

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col">
      <Link
        to={backTo}
        className="inline-flex w-fit items-center gap-1.5 rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
      >
        <ArrowLeft className="size-3.5" />
        Back to Company Brain
      </Link>

      <header className="mt-6">
        <h1 className="type-display-lg text-fg">New knowledge document</h1>
        <p className="measure mt-2 text-[14px] leading-relaxed text-fg-muted">
          Anything stored here can be retrieved to answer a question in this
          workspace. Personal information is removed before it is stored.
        </p>
      </header>

      <form onSubmit={handleSubmit} className="mt-10 flex flex-col">
        {/* How it gets filed. Kept together and kept quiet — these are
            three small decisions, not three-quarters of the task. */}
        <div className="grid gap-5 border-y border-line py-6 sm:grid-cols-[1fr_7rem]">
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
            hint="1 or higher."
          />
          <Input
            className="sm:col-span-2"
            label="Source"
            required
            placeholder="e.g. SOC-2 policy revision, incident INC-1234 postmortem…"
            value={form.provenance}
            onChange={(e) => setForm({ ...form, provenance: e.target.value })}
            error={errors.provenance}
            disabled={mutation.isPending}
            hint="Where this knowledge comes from. It becomes the document's identity, and it is what a reader sees cited in an answer."
          />
        </div>

        {/* The document itself. */}
        <div className="mt-8">
          <Textarea
            label="Content"
            required
            rows={18}
            placeholder="The knowledge itself — the body of the policy, procedure, or note…"
            value={form.content}
            onChange={(e) => setForm({ ...form, content: e.target.value })}
            error={errors.content}
            disabled={mutation.isPending}
            textareaClassName="font-mono text-[13.5px] leading-relaxed"
          />
          <p className="mt-2 text-right text-[12px] tabular-nums text-fg-muted">
            {words === 0
              ? 'Empty'
              : `${words.toLocaleString()} ${words === 1 ? 'word' : 'words'}`}
          </p>
        </div>

        {errors.api && (
          <div className="mt-6">
            <InlineError>{errors.api}</InlineError>
          </div>
        )}

        <div className="mt-8 flex items-center justify-end gap-2 border-t border-line pt-5">
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
            Create document
          </Button>
        </div>
      </form>
    </div>
  )
}
