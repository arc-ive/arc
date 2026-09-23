import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { ArrowLeft, BookOpen, FileText, SearchX, Edit, Save, X, Loader2 } from 'lucide-react'
import { getKnowledgeDocument, updateKnowledge } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { STALLED_MESSAGE, isQueryFailed, isQueryLoading } from '../../api/queryState.js'
import { sourceLabels, sourceVariants, KNOWLEDGE_SOURCES } from '../../lib/sources.js'
import { formatDateTime } from '../../lib/format.js'
import { Card, CardHeader, CardContent } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { Select } from '../../components/ui/Select.jsx'

export function KnowledgeDetailPage() {
  const { tenantId, documentId } = useParams()
  const queryClient = useQueryClient()
  const [isEditing, setIsEditing] = useState(false)
  const [formData, setFormData] = useState({
    source: '',
    provenance: '',
    content: '',
    status: '',
  })

  const documentQuery = useQuery({
    queryKey: queryKeys.knowledgeDocument(tenantId, documentId),
    queryFn: () => getKnowledgeDocument(tenantId, documentId),
    enabled: Boolean(tenantId && documentId),
  })

  const updateMutation = useMutation({
    mutationFn: (payload) => updateKnowledge(tenantId, documentId, payload),
    onSuccess: (updatedDoc) => {
      queryClient.setQueryData(queryKeys.knowledgeDocument(tenantId, documentId), updatedDoc)
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge(tenantId) })
      setIsEditing(false)
    },
    onError: (error) => {
      console.error('Failed to update knowledge document:', error)
    },
  })

  const doc = documentQuery.data

  useEffect(() => {
    if (doc) {
      setFormData({
        source: doc.source,
        provenance: doc.provenance,
        content: doc.content || '',
        status: doc.status,
      })
    }
  }, [doc])

  const backTo = `/app/t/${encodeURIComponent(tenantId)}/knowledge`

  if (isQueryLoading(documentQuery)) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        <Skeleton className="h-4 w-40" />
        <div className="flex flex-col gap-4">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
        </div>
        <Card className="p-6">
          <SkeletonText lines={8} />
        </Card>
      </div>
    )
  }

  if (isQueryFailed(documentQuery)) {
    const failure = documentQuery.error
    const forbidden = failure?.status === 403
    const notFound = failure?.status === 404
    return (
      <div className="mx-auto max-w-3xl">
        <Link
          to={backTo}
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <ArrowLeft className="size-3.5" />
          Back to Company Brain
        </Link>
        <Card>
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
        </Card>
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="mx-auto max-w-3xl">
        <Link
          to={backTo}
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <ArrowLeft className="size-3.5" />
          Back to Company Brain
        </Link>
        <Card>
          <EmptyState
            icon={SearchX}
            title="Document not found"
            description="This document does not exist or is not accessible in this tenant."
            action={
              <Link to={backTo}>
                <Button variant="secondary" size="sm">
                  <ArrowLeft className="size-3.5" />
                  Back to Company Brain
                </Button>
              </Link>
            }
          />
        </Card>
      </div>
    )
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const payload = {}
    if (formData.source !== doc.source) payload.source = formData.source
    if (formData.provenance !== doc.provenance) payload.provenance = formData.provenance
    if (formData.content !== doc.content) payload.content = formData.content
    if (formData.status !== doc.status) payload.status = formData.status
    if (Object.keys(payload).length > 0) {
      updateMutation.mutate(payload)
    } else {
      setIsEditing(false)
    }
  }

  const handleCancel = () => {
    setFormData({
      source: doc.source,
      provenance: doc.provenance,
      content: doc.content || '',
      status: doc.status,
    })
    setIsEditing(false)
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <section>
        <Link
          to={backTo}
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-fg-muted transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <ArrowLeft className="size-3.5" />
          Back to Company Brain
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <BookOpen className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-xl font-semibold tracking-tight text-zinc-100 sm:text-2xl">
              {doc.provenance || 'Untitled document'}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Badge variant={sourceVariants[doc.source] ?? 'neutral'}>
                {sourceLabels[doc.source] ?? doc.source}
              </Badge>
              <Badge size="sm" dot variant={doc.status === 'active' ? 'green' : 'neutral'}>
                {doc.status}
              </Badge>
              <span className="font-mono text-xs text-fg-muted">
                v{doc.version}
              </span>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {isEditing ? (
              <>
                <Button type="button" variant="ghost" size="sm" onClick={handleCancel} disabled={updateMutation.isPending}>
                  <X className="size-3.5" />
                  Cancel
                </Button>
                <Button type="submit" form="knowledge-edit-form" disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                  Save
                </Button>
              </>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => setIsEditing(true)}>
                <Edit className="size-3.5" />
                Edit
              </Button>
            )}
          </div>
        </div>
      </section>

      <form id="knowledge-edit-form" onSubmit={handleSubmit}>
        {isEditing ? (
          <>
            <Card className="overflow-hidden">
              <CardHeader title="Content" />
              <CardContent className="py-5">
                <Textarea
                  value={formData.content}
                  onChange={(e) => setFormData({ ...formData, content: e.target.value })}
                  className="font-mono text-[13px] min-h-[200px]"
                  placeholder="Enter document content"
                  required
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader title="Properties" />
              <CardContent className="py-4 space-y-4">
                <div>
                  <label htmlFor="edit-source" className="block text-sm font-medium text-zinc-300 mb-1">
                    Source
                  </label>
                  <Select
                    id="edit-source"
                    value={formData.source}
                    onChange={(e) => setFormData({ ...formData, source: e.target.value })}
                    required
                  >
                    {KNOWLEDGE_SOURCES.map((s) => (
                      <option key={s} value={s}>
                        {sourceLabels[s] ?? s}
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <label htmlFor="edit-provenance" className="block text-sm font-medium text-zinc-300 mb-1">
                    Provenance
                  </label>
                  <input
                    id="edit-provenance"
                    type="text"
                    value={formData.provenance}
                    onChange={(e) => setFormData({ ...formData, provenance: e.target.value })}
                    className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    required
                    minLength={1}
                  />
                </div>
                <div>
                  <label htmlFor="edit-status" className="block text-sm font-medium text-zinc-300 mb-1">
                    Status
                  </label>
                  <Select
                    id="edit-status"
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                  >
                    <option value="active">Active</option>
                    <option value="archived">Archived</option>
                  </Select>
                </div>
              </CardContent>
            </Card>
          </>
        ) : (
          <>
            <Card className="overflow-hidden">
              <CardHeader title="Content" />
              <CardContent className="py-5">
                {doc.content ? (
                  <div className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-zinc-300">
                    {doc.content}
                  </div>
                ) : (
                  <p className="text-sm text-fg-muted">This document has no content.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader title="Metadata" />
              <CardContent className="py-4">
                <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-[13px] text-fg-muted">Source</dt>
                    <dd className="font-mono text-xs text-zinc-300">{doc.source}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-[13px] text-fg-muted">Version</dt>
                    <dd className="font-mono text-xs text-zinc-300">{doc.version}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-4 sm:col-span-2">
                    <dt className="text-[13px] text-fg-muted">Document ID</dt>
                    <dd className="truncate font-mono text-xs text-zinc-400">
                      {doc.id}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-[13px] text-fg-muted">Created</dt>
                    <dd className="text-xs text-zinc-400">
                      {formatDateTime(doc.created_at)}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-[13px] text-fg-muted">Updated</dt>
                    <dd className="text-xs text-zinc-400">
                      {formatDateTime(doc.updated_at)}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </>
        )}
      </form>

      <div className="flex items-center gap-2 text-xs text-fg-muted">
        <FileText className="size-3.5" />
        Stored as plain text. Retrieval and grounding are handled by the
        backend.
      </div>
    </div>
  )
}