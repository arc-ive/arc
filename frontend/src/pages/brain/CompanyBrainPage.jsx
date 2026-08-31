import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, FilePlus2, Search, X } from 'lucide-react'
import { useAuth } from '../../auth/useAuth.js'
import { getKnowledge, searchKnowledge, KNOWLEDGE_SOURCES } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { sourceLabels, sourceVariants } from '../../lib/sources.js'
import { truncate, relativeTime } from '../../lib/format.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Tabs } from '../../components/ui/Tabs.jsx'
import { EmptyState } from '../../components/ui/EmptyState.jsx'
import { ErrorState } from '../../components/ui/ErrorState.jsx'
import { SkeletonCard } from '../../components/ui/Skeleton.jsx'
import { cn } from '../../lib/cn.js'

/**
 * Company Brain — the central knowledge surface.
 *
 * The information architecture mirrors the backend's real knowledge source
 * taxonomy (TRD 9.2): policies, procedures, incident reports,
 * troubleshooting documents, internal knowledge, and historical solutions.
 * The "Sources & provenance" tab summarizes where knowledge comes from.
 */
const BRAIN_TABS = [
  { value: 'all', label: 'Knowledge' },
  { value: 'procedure', label: 'Procedures' },
  { value: 'policy', label: 'Policies' },
  { value: 'incident_report', label: 'Incidents' },
  { value: 'solution', label: 'Solutions' },
  { value: 'troubleshooting', label: 'Troubleshooting' },
  { value: 'internal_knowledge', label: 'Internal' },
  { value: 'sources', label: 'Sources & provenance' },
]

function useDebounced(value, delay = 200) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export function CompanyBrainPage() {
  const { tenantId } = useParams()
  const navigate = useNavigate()
  const { isDemo } = useAuth()
  const { can } = useCapabilities()
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounced(query)

  const knowledge = useQuery({
    queryKey: queryKeys.knowledge(tenantId),
    queryFn: () => getKnowledge(tenantId),
    enabled: !isDemo && Boolean(tenantId),
  })

  const search = useQuery({
    queryKey: queryKeys.knowledgeSearch(tenantId, debouncedQuery, 20),
    queryFn: () => searchKnowledge(tenantId, debouncedQuery, 20),
    enabled: !isDemo && Boolean(tenantId) && Boolean(debouncedQuery.trim()),
  })

  const canCreate = can('knowledge:create')

  const documents = knowledge.data ?? []

  const filtered = documents.filter((doc) => {
    const matchesTab = tab === 'all' || tab === 'sources' || doc.source === tab
    const q = debouncedQuery.trim().toLowerCase()
    const matchesQuery =
      !q ||
      (doc.provenance ?? '').toLowerCase().includes(q) ||
      (doc.content ?? '').toLowerCase().includes(q)
    return matchesTab && matchesQuery
  })

  const sourceCounts = documents.reduce((counts, doc) => {
    counts[doc.source] = (counts[doc.source] ?? 0) + 1
    return counts
  }, {})

  const hasFilters = Boolean(query.trim())
  const isSearching = Boolean(debouncedQuery.trim())

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
            Company Brain
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            The company&apos;s intelligence — knowledge, procedures, policies,
            decisions, incidents, and solutions with provenance.
          </p>
        </div>
        {canCreate && (
          <Button onClick={() => navigate('new')}>
            <FilePlus2 className="size-4" />
            New document
          </Button>
        )}
      </section>

      <Tabs tabs={BRAIN_TABS} active={tab} onChange={setTab} size="sm" className="max-w-full overflow-x-auto" />

      <section className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-600" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search provenance and content…"
            aria-label="Search knowledge"
            className={cn(
              'h-9 w-full rounded-lg border border-zinc-800 bg-zinc-900/70 pl-9 pr-8 text-sm text-zinc-100',
              'placeholder:text-zinc-500 transition-colors duration-150',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400',
              'hover:border-zinc-700',
            )}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-500 transition-colors duration-150 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </section>

      {knowledge.isPending && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {knowledge.isError && (
        <Card>
          <ErrorState
            title="Could not load the knowledge base"
            message={errorMessage(knowledge.error)}
            onRetry={() => knowledge.refetch()}
            error={knowledge.error}
          />
        </Card>
      )}

      {!knowledge.isPending &&
        !knowledge.isError &&
        knowledge.data?.length === 0 && (
          <Card>
            <EmptyState
              icon={BookOpen}
              title="The Company Brain is empty"
              description="Add the first knowledge document — a policy, procedure, or troubleshooting note the tenant's AI can draw on."
              action={
                canCreate ? (
                  <Button onClick={() => navigate('new')}>
                    <FilePlus2 className="size-4" />
                    Create document
                  </Button>
                ) : undefined
              }
            />
          </Card>
        )}

      {!knowledge.isPending &&
        !knowledge.isError &&
        knowledge.data?.length > 0 &&
        tab === 'sources' && !isSearching && (
          <Card className="overflow-hidden">
            <CardHeader
              title="Sources &amp; provenance"
              description="Where the company's intelligence comes from, by source category (backend taxonomy)."
            />
            <CardContent className="grid gap-3 sm:grid-cols-2">
              {KNOWLEDGE_SOURCES.map((source) => {
                const count = sourceCounts[source] ?? 0
                return (
                  <button
                    key={source}
                    type="button"
                    onClick={() => setTab(source)}
                    className="flex items-center gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-4 py-3 text-left transition-colors duration-150 hover:border-zinc-700 hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
                  >
                    <Badge variant={sourceVariants[source] ?? 'neutral'}>
                      {sourceLabels[source] ?? source}
                    </Badge>
                    <span className="ml-auto font-mono text-xs text-zinc-400">
                      {count}
                    </span>
                  </button>
                )
              })}
            </CardContent>
          </Card>
        )}

      {isSearching &&
        !search.isPending &&
        !search.isError &&
        search.data?.length === 0 && (
          <Card>
            <EmptyState
              icon={Search}
              title="No results found"
              description="No knowledge chunks match your search."
              action={
                <Button variant="secondary" size="sm" onClick={() => setQuery('')}>
                  Clear search
                </Button>
              }
            />
          </Card>
        )}

      {isSearching &&
        !search.isPending &&
        !search.isError &&
        search.data?.length > 0 && (
          <section className="grid gap-4 sm:grid-cols-2">
            {search.data.map((chunk) => (
              <Card
                key={chunk.chunk_id}
                hover
                className="group flex cursor-pointer flex-col gap-3 p-5"
                onClick={() => navigate(`../knowledge/${chunk.document_id}`)}
                role="link"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') navigate(`../knowledge/${chunk.document_id}`)
                }}
              >
                <div className="flex items-center justify-between gap-3">
                  <Badge variant={sourceVariants[chunk.source] ?? 'neutral'}>
                    {sourceLabels[chunk.source] ?? chunk.source}
                  </Badge>
                  <span className="font-mono text-[11px] text-zinc-600">
                    v{chunk.document_version}
                  </span>
                </div>
                <p className="text-sm font-medium leading-snug text-zinc-100">
                  {chunk.provenance || 'Untitled document'}
                </p>
                <p className="line-clamp-3 text-[13px] leading-relaxed text-zinc-500">
                  {truncate(chunk.content, 240)}
                </p>
                <div className="mt-auto flex items-center justify-between pt-1">
                  <span className="text-xs text-zinc-600">
                    Similarity: {(chunk.similarity * 100).toFixed(1)}%
                  </span>
                  <Badge variant="indigo" size="sm" dot>
                    Search result
                  </Badge>
                </div>
              </Card>
            ))}
          </section>
        )}

      {!isSearching &&
        filtered.length === 0 &&
        !knowledge.isPending &&
        !knowledge.isError &&
        knowledge.data?.length > 0 &&
        tab !== 'sources' && (
          <Card>
            <EmptyState
              icon={Search}
              title="No matching documents"
              description={
                hasFilters
                  ? 'No documents match the current search.'
                  : tab === 'all'
                    ? 'No knowledge documents yet.'
                    : `No ${tab.replace(/_/g, ' ')} documents yet.`
              }
              action={
                hasFilters ? (
                  <Button variant="secondary" size="sm" onClick={() => setQuery('')}>
                    Clear search
                  </Button>
                ) : canCreate ? (
                  <Button size="sm" onClick={() => navigate('new')}>
                    <FilePlus2 className="size-4" />
                    Add document
                  </Button>
                ) : undefined
              }
            />
          </Card>
        )}

      {!isSearching &&
        filtered.length > 0 &&
        tab !== 'sources' && (
          <section className="grid gap-4 sm:grid-cols-2">
            {filtered.map((doc) => (
              <Card
                key={doc.id}
                hover
                className="group flex cursor-pointer flex-col gap-3 p-5"
                onClick={() => navigate(doc.id)}
                role="link"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') navigate(doc.id)
                }}
              >
                <div className="flex items-center justify-between gap-3">
                  <Badge variant={sourceVariants[doc.source] ?? 'neutral'}>
                    {sourceLabels[doc.source] ?? doc.source}
                  </Badge>
                  <span className="font-mono text-[11px] text-zinc-600">
                    v{doc.version}
                  </span>
                </div>
                <p className="text-sm font-medium leading-snug text-zinc-100">
                  {doc.provenance || 'Untitled document'}
                </p>
                <p className="line-clamp-3 text-[13px] leading-relaxed text-zinc-500">
                  {truncate(doc.content, 240)}
                </p>
                <div className="mt-auto flex items-center justify-between pt-1">
                  <span className="text-xs text-zinc-600">
                    Updated {relativeTime(doc.updated_at)}
                  </span>
                  <Badge
                    variant={doc.status === 'active' ? 'green' : 'neutral'}
                    size="sm"
                    dot
                  >
                    {doc.status}
                  </Badge>
                </div>
              </Card>
            ))}
          </section>
        )}


    </div>
  )
}