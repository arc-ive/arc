import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BookOpen, FilePlus2, Search, X } from 'lucide-react'
import { getKnowledge, searchKnowledge, KNOWLEDGE_SOURCES } from '../../api/endpoints/knowledge.js'
import { queryKeys } from '../../api/queryKeys.js'
import { errorMessage } from '../../api/errors.js'
import { sourceLabels, sourceVariants } from '../../lib/sources.js'
import { useCapabilities } from '../../auth/capabilities.js'
import { Button } from '../../components/ui/Button.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Badge } from '../../components/ui/Badge.jsx'
import { Tabs } from '../../components/ui/Tabs.jsx'
import { DocumentRow } from './DocumentRow.jsx'
import { useDocumentTitle } from '../../lib/useDocumentTitle.js'
import { groupChunksByDocument, bestPassage } from '../../lib/knowledge.js'
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
  { value: 'incident_report', label: 'Incident reports' },
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
  useDocumentTitle('Company Brain')
  const { tenantId } = useParams()
  const navigate = useNavigate()
  const { can } = useCapabilities()
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounced(query)

  const knowledge = useQuery({
    queryKey: queryKeys.knowledge(tenantId),
    queryFn: () => getKnowledge(tenantId),
    enabled: Boolean(tenantId),
  })

  const search = useQuery({
    queryKey: queryKeys.knowledgeSearch(tenantId, debouncedQuery, 20),
    queryFn: () => searchKnowledge(tenantId, debouncedQuery, 20),
    enabled: Boolean(tenantId) && Boolean(debouncedQuery.trim()),
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
      {/* The description said "The company's intelligence — knowledge,
          procedures, policies, decisions, incidents, and solutions with
          provenance." Two lines of category list under a title that
          already says what this is. The count below is a fact; the
          sentence was not. */}
      <header className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <h1 className="type-display-lg text-fg">Company Brain</h1>
          {!knowledge.isPending && documents.length > 0 && (
            <p className="mt-2 text-[14px] text-fg-muted">
              {documents.length}{' '}
              {documents.length === 1 ? 'document' : 'documents'} Arc can
              answer from
            </p>
          )}
        </div>
        {canCreate && (
          <Button onClick={() => navigate('new')}>
            <FilePlus2 className="size-4" />
            New document
          </Button>
        )}
      </header>

      {/* Search and filters share one line: they are the same job — narrow
          the index — and stacking them cost a third of the fold. */}
      <section className="flex flex-col gap-4 lg:flex-row lg:items-center lg:gap-8">
        <div className="relative min-w-0 lg:w-[22rem]">
          <Search className="pointer-events-none absolute left-0 top-1/2 size-4 -translate-y-1/2 text-fg-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search this workspace’s knowledge"
            aria-label="Search knowledge"
            className={cn(
              'h-12 w-full border-b border-line bg-transparent pl-8 pr-8 text-[15px] text-fg',
              'placeholder:text-fg-muted transition-colors duration-150',
              'focus:border-fg focus-visible:outline-none',
            )}
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-0 top-1/2 -translate-y-1/2 rounded p-1 text-fg-muted transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
        <div className="min-w-0 flex-1 overflow-x-auto">
          <Tabs tabs={BRAIN_TABS} active={tab} onChange={setTab} size="sm" />
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
                    className="flex items-center gap-3 rounded-lg border border-line/70 bg-surface px-4 py-3 text-left transition-colors duration-150 hover:border-line-strong hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
                  >
                    <Badge variant={sourceVariants[source] ?? 'neutral'}>
                      {sourceLabels[source] ?? source}
                    </Badge>
                    <span className="ml-auto font-mono text-xs text-fg-muted">
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
              description="No documents match your search."
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
          <section className="stagger border-t border-line">
            {groupChunksByDocument(search.data).map((doc, i) => (
              <DocumentRow
                key={doc.documentId}
                index={i}
                to={doc.documentId}
                query={debouncedQuery}
                passageCount={doc.passages.length}
                document={{
                  ...doc,
                  id: doc.documentId,
                  passage: bestPassage(doc.passages, debouncedQuery),
                }}
              />
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
          <section className="stagger border-t border-line">
            {filtered.map((doc, i) => (
              <DocumentRow
                key={doc.id}
                index={i}
                to={doc.id}
                document={{ ...doc, passage: doc.content }}
              />
            ))}
          </section>
        )}

    </div>
  )
}