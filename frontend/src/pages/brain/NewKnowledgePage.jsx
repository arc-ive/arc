import { useState } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import {
  createKnowledge,
  uploadKnowledge,
  KNOWLEDGE_SOURCES,
} from '../../api/endpoints/knowledge.js'
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
  // A chosen file replaces the typed content entirely. Keeping both
  // would leave the page ambiguous about which one is the document.
  const [file, setFile] = useState(null)

  const mutation = useMutation({
    mutationFn: () =>
      file
        ? uploadKnowledge(tenantId, {
            file,
            source: form.source,
            // Blank falls back to the filename server-side, which is the
            // only human name an upload carries.
            provenance: form.provenance.trim() || undefined,
          })
        : createKnowledge(tenantId, {
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
    // An upload supplies both: the file is the content, and the filename
    // stands in for the source when none is typed.
    if (!file && !form.provenance.trim()) {
      next.provenance = 'Source is required.'
    }
    if (!file && !form.content.trim()) {
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
          {/* Hidden for an upload: that path always creates version 1,
              so an editable field here would be input the server
              silently ignores. */}
          {!file && (
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
          )}
          <Input
            className="sm:col-span-2"
            label="Source"
            required={!file}
            placeholder="e.g. SOC-2 policy revision, incident INC-1234 postmortem…"
            value={form.provenance}
            onChange={(e) => setForm({ ...form, provenance: e.target.value })}
            error={errors.provenance}
            disabled={mutation.isPending}
            hint={
              file
                ? "Optional for an upload — the filename is used when this is blank. It becomes the document's identity, and it is what a reader sees cited in an answer."
                : "Where this knowledge comes from. It becomes the document's identity, and it is what a reader sees cited in an answer."
            }
          />
        </div>

        {/* The document itself — typed, or a file. A chosen file replaces
            the editor entirely rather than sitting beside it, because two
            possible sources of content on one page is a question the page
            cannot answer. */}
        {file ? (
          <div className="mt-8 border-y border-line py-6">
            <p className="type-label text-fg-muted">File</p>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="font-mono text-[14px] text-fg">{file.name}</span>
              <span className="text-[12.5px] tabular-nums text-fg-muted">
                {(file.size / 1024).toFixed(0)} KB
              </span>
              <button
                type="button"
                onClick={() => setFile(null)}
                disabled={mutation.isPending}
                className="rounded text-[13px] text-fg-muted underline underline-offset-2 transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
              >
                Remove
              </button>
            </div>
            <p className="measure mt-3 text-[12.5px] leading-relaxed text-fg-muted">
              Arc reads the text out of this file and stores that. Plain
              text, Markdown, PDF and Word are supported. Scanned images
              are not — Arc would have nothing to read, and would say so
              rather than store an empty document.
            </p>
          </div>
        ) : (
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
            <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
              <label className="cursor-pointer rounded text-[13px] text-fg-muted underline underline-offset-2 transition-colors duration-150 hover:text-fg focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-indigo-400">
                Upload a file instead
                <input
                  type="file"
                  className="sr-only"
                  accept=".txt,.md,.markdown,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  disabled={mutation.isPending}
                  onChange={(e) => {
                    const chosen = e.target.files?.[0]
                    if (chosen) setFile(chosen)
                    // Reset so choosing the same file twice still fires.
                    e.target.value = ''
                  }}
                />
              </label>
              <p className="text-[12px] tabular-nums text-fg-muted">
                {words === 0
                  ? 'Empty'
                  : `${words.toLocaleString()} ${words === 1 ? 'word' : 'words'}`}
              </p>
            </div>
          </div>
        )}

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
