import { Link, useParams } from 'react-router-dom'
import { documentTitle } from '../../lib/knowledge.js'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { getKnowledgeDocument, updateKnowledge } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { STALLED_MESSAGE, isQueryFailed, isQueryLoading } from '../../api/queryState.js'
import { sourceLabels, KNOWLEDGE_SOURCES } from '../../lib/sources.js'
import { formatDateTime } from '../../lib/format.js'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Select } from '../../components/ui/Select.jsx'
import { Input } from '../../components/ui/Input.jsx'
import { Section, DataRow } from '../../components/layout/Section.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'

/**
 * One document in the Company Brain.
 *
 * Recomposed as a document rather than as three stacked cards titled
 * "Content", "Properties" and "Metadata". The writing is the subject, so
 * it gets the page; how it is filed sits under it, where a reader who
 * needs it will look and a reader who doesn't is not obstructed by it.
 *
 * Two defects went with the composition:
 *
 *  - A failed save was reported only to the browser console. The dialog
 *    closed on success and simply did nothing on failure, so a person
 *    could believe an edit had been stored when it had not. It is now
 *    shown, and edit mode stays open so the writing is not lost.
 *  - The edit form was seeded by an effect watching the document, which
 *    re-ran on every refetch and could overwrite what someone was typing.
 *    The draft is now created when editing starts — which also retires
 *    the file's standing set-state-in-effect lint warning.
 */
export function KnowledgeDetailPage() {
  const { tenantId, documentId } = useParams()
  const queryClient = useQueryClient()

  // `null` means "not editing". Holding the draft itself as the mode flag
  // removes the need to keep two pieces of state agreeing with each other.
  const [draft, setDraft] = useState(null)

  const documentQuery = useQuery({
    queryKey: queryKeys.knowledgeDocument(tenantId, documentId),
    queryFn: () => getKnowledgeDocument(tenantId, documentId),
    enabled: Boolean(tenantId && documentId),
  })

  const updateMutation = useMutation({
    mutationFn: (payload) => updateKnowledge(tenantId, documentId, payload),
    onSuccess: (updatedDoc) => {
      queryClient.setQueryData(
        queryKeys.knowledgeDocument(tenantId, documentId),
        updatedDoc,
      )
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge(tenantId) })
      setDraft(null)
    },
  })

  const doc = documentQuery.data
  useDocumentTitle(doc ? documentTitle(doc) : 'Document')

  const backTo = `/app/t/${encodeURIComponent(tenantId)}/knowledge`

  const backLink = (
    <Link
      to={backTo}
      className="inline-flex w-fit items-center gap-1.5 rounded text-[13px] text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
    >
      <ArrowLeft className="size-3.5" />
      Back to Company Brain
    </Link>
  )

  if (isQueryLoading(documentQuery)) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col">
        {backLink}
        <div className="mt-6 flex flex-col gap-3">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
        </div>
        <div className="mt-10 border-t border-line pt-8">
          <SkeletonText lines={10} />
        </div>
      </div>
    )
  }

  if (isQueryFailed(documentQuery)) {
    const failure = documentQuery.error
    const forbidden = failure?.status === 403
    const notFound = failure?.status === 404
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col">
        {backLink}
        <div className="mt-8">
          <ErrorState
            title={
              forbidden
                ? 'Permission denied'
                : notFound
                  ? 'Document not found'
                  : 'Could not load this document'
            }
            message={
              forbidden
                ? 'You do not have read access to this tenant’s knowledge base.'
                : notFound
                  ? 'This document does not exist, or it has been deleted.'
                  : failure
                    ? errorMessage(failure)
                    : STALLED_MESSAGE
            }
            onRetry={() => documentQuery.refetch()}
            error={failure}
          />
        </div>
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-col">
        {backLink}
        <h1 className="mt-6 type-display text-fg">Document not found</h1>
        <p className="measure mt-3 type-prose text-fg-subtle">
          This document does not exist or is not accessible in this tenant.
        </p>
      </div>
    )
  }

  const isEditing = draft !== null

  const startEditing = () =>
    setDraft({
      source: doc.source,
      provenance: doc.provenance,
      content: doc.content || '',
      status: doc.status,
    })

  const handleSubmit = (e) => {
    e.preventDefault()
    const payload = {}
    if (draft.source !== doc.source) payload.source = draft.source
    if (draft.provenance !== doc.provenance) payload.provenance = draft.provenance
    if (draft.content !== doc.content) payload.content = draft.content
    if (draft.status !== doc.status) payload.status = draft.status
    if (Object.keys(payload).length > 0) {
      updateMutation.mutate(payload)
    } else {
      setDraft(null)
    }
  }

  const handleCancel = () => {
    updateMutation.reset()
    setDraft(null)
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col">
      {backLink}

      <header className="mt-6 flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        <div className="min-w-0 flex-1">
          <h1 className="type-display text-fg">{documentTitle(doc)}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
            <Badge variant="neutral" size="sm">
              {sourceLabels[doc.source] ?? doc.source}
            </Badge>
            <Badge
              size="sm"
              dot
              variant={doc.status === 'active' ? 'success' : 'neutral'}
            >
              {doc.status}
            </Badge>
            <span className="font-mono text-[12px] text-fg-muted">
              v{doc.version}
            </span>
            <span className="text-[12.5px] text-fg-muted">
              Updated {formatDateTime(doc.updated_at)}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {isEditing ? (
            <>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={handleCancel}
                disabled={updateMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                form="knowledge-edit-form"
                size="sm"
                isLoading={updateMutation.isPending}
                loadingText="Saving…"
              >
                Save
              </Button>
            </>
          ) : (
            <Button variant="secondary" size="sm" onClick={startEditing}>
              Edit
            </Button>
          )}
        </div>
      </header>

      {/* A failed save must not look like nothing happened, and must not
          take the writing with it — edit mode stays open. */}
      {updateMutation.isError && (
        <div className="mt-6">
          <InlineError>
            This document could not be saved. {errorMessage(updateMutation.error)}
          </InlineError>
        </div>
      )}

      {isEditing ? (
        <form
          id="knowledge-edit-form"
          onSubmit={handleSubmit}
          className="mt-8 flex flex-col"
        >
          <Textarea
            label="Content"
            value={draft.content}
            onChange={(e) => setDraft({ ...draft, content: e.target.value })}
            textareaClassName="font-mono text-[13.5px] leading-relaxed"
            rows={18}
            placeholder="Enter document content"
            required
          />

          <div className="mt-8 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
            <Select
              label="Document type"
              value={draft.source}
              onChange={(e) => setDraft({ ...draft, source: e.target.value })}
              required
            >
              {KNOWLEDGE_SOURCES.map((s) => (
                <option key={s} value={s}>
                  {sourceLabels[s] ?? s}
                </option>
              ))}
            </Select>
            <Select
              label="Status"
              value={draft.status}
              onChange={(e) => setDraft({ ...draft, status: e.target.value })}
            >
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </Select>
            <Input
              className="sm:col-span-2"
              label="Source"
              value={draft.provenance}
              onChange={(e) => setDraft({ ...draft, provenance: e.target.value })}
              required
              minLength={1}
              hint="Where this document came from — a system, a team, or a person."
            />
          </div>
        </form>
      ) : (
        <>
          <article className="mt-8 border-t border-line pt-8">
            {doc.content ? (
              <div className="whitespace-pre-wrap font-mono text-[13.5px] leading-relaxed text-fg-subtle">
                {doc.content}
              </div>
            ) : (
              <p className="text-[14px] text-fg-muted">
                This document has no content.
              </p>
            )}
          </article>

          <Section title="Filed as" className="mt-14">
            <dl className="border-t border-line">
              <DataRow label="Document type">
                <span className="font-mono text-[13px]">{doc.source}</span>
              </DataRow>
              {/* Only when it is not already the heading. A human-written
                  provenance IS the title, and printing it twice on one
                  page tells the reader nothing the second time. A
                  connector-written one ("connector:github:arc-ive/arc/…")
                  is reduced to a readable label up there, so the raw
                  string is still worth showing here. */}
              {doc.provenance && doc.provenance.trim() !== documentTitle(doc) && (
                <DataRow label="Source">
                  <span className="break-all font-mono text-[12.5px]">
                    {doc.provenance}
                  </span>
                </DataRow>
              )}
              <DataRow label="Version">
                <span className="font-mono text-[13px]">{doc.version}</span>
              </DataRow>
              <DataRow label="Created">{formatDateTime(doc.created_at)}</DataRow>
              <DataRow label="Identifier">
                <span className="break-all font-mono text-[12.5px] text-fg-muted">
                  {doc.id}
                </span>
              </DataRow>
            </dl>
          </Section>

          <p className="measure mt-8 text-[12.5px] leading-relaxed text-fg-muted">
            Stored as plain text. Retrieval and grounding happen in the
            backend, so what is written here is what an answer can cite.
          </p>
        </>
      )}
    </div>
  )
}
