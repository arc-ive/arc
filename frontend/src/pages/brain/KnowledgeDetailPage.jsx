import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, FileText, SearchX } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getKnowledgeDocument } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { sourceLabels, sourceVariants } from '../../lib/sources.js'
import { formatDateTime } from '../../lib/format.js'
import { Card, CardHeader, CardContent } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton.jsx'

export function KnowledgeDetailPage() {
  const { tenantId, documentId } = useParams()
  const { isDemo } = useAuth()

  const documentQuery = useQuery({
    queryKey: queryKeys.knowledgeDocument(tenantId, documentId),
    queryFn: () => getKnowledgeDocument(tenantId, documentId),
    enabled: !isDemo && Boolean(tenantId && documentId),
  })

  const backTo = `/app/t/${encodeURIComponent(tenantId)}/knowledge`
  const doc = documentQuery.data

  if (documentQuery.isPending) {
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

  if (documentQuery.isError) {
    const forbidden = documentQuery.error?.status === 403
    return (
      <div className="mx-auto max-w-3xl">
        <Link
          to={backTo}
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-zinc-500 transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
        >
          <ArrowLeft className="size-3.5" />
          Back to Company Brain
        </Link>
        <Card>
          <ErrorState
            title={
              forbidden
                ? 'Permission denied'
                : 'Could not load this document'
            }
            message={
              forbidden
                ? 'You do not have read access to this tenant’s knowledge base.'
                : errorMessage(documentQuery.error)
            }
            onRetry={() => documentQuery.refetch()}
            error={documentQuery.error}
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
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-zinc-500 transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
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

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <section>
        <Link
          to={backTo}
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-zinc-500 transition-colors duration-150 hover:text-zinc-200 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
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
              <span className="font-mono text-xs text-zinc-600">
                v{doc.version}
              </span>
            </div>
          </div>
        </div>
      </section>

      <Card className="overflow-hidden">
        <CardHeader title="Content" />
        <CardContent className="py-5">
          {doc.content ? (
            <div className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-zinc-300">
              {doc.content}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">This document has no content.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader title="Metadata" />
        <CardContent className="py-4">
          <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
            <div className="flex items-center justify-between gap-4">
              <dt className="text-[13px] text-zinc-500">Source</dt>
              <dd className="font-mono text-xs text-zinc-300">{doc.source}</dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-[13px] text-zinc-500">Version</dt>
              <dd className="font-mono text-xs text-zinc-300">{doc.version}</dd>
            </div>
            <div className="flex items-center justify-between gap-4 sm:col-span-2">
              <dt className="text-[13px] text-zinc-500">Document ID</dt>
              <dd className="truncate font-mono text-xs text-zinc-400">
                {doc.id}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-[13px] text-zinc-500">Created</dt>
              <dd className="text-xs text-zinc-400">
                {formatDateTime(doc.created_at)}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4">
              <dt className="text-[13px] text-zinc-500">Updated</dt>
              <dd className="text-xs text-zinc-400">
                {formatDateTime(doc.updated_at)}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <div className="flex items-center gap-2 text-xs text-zinc-600">
        <FileText className="size-3.5" />
        Stored as plain text. Retrieval and grounding are handled by the
        backend.
      </div>
    </div>
  )
}