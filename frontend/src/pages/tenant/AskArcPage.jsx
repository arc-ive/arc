import { useState, useRef } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Loader2,
  Sparkles,
  RotateCcw,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { parseCitations, groundingSummary } from '../../lib/citations.js'
import { Button } from '../../components/ui/Button.jsx'
import { cn } from '../../lib/cn.js'
import { useTypewriter } from '../../lib/useTypewriter.js'
import { useTenant } from '../../tenant/useTenant.js'
import { queryIntelligence } from '../../api/endpoints/intelligence.js'
import { getKnowledge } from '../../api/endpoints/knowledge.js'
import { sourceLabels } from '../../lib/sources.js'
import { Select } from '../../components/ui/Select.jsx'
import { queryKeys } from '../../api/queryKeys.js'
import { documentTitle } from '../../lib/knowledge.js'
import { Skeleton } from '../../components/ui/Skeleton.jsx'
import { toApiError } from '../../api/errors.js'

/**
 * The questions that type themselves into the empty field.
 *
 * Chosen to show the RANGE of what Arc answers rather than to be clicked:
 * a policy lookup, a change, an incident, a procedure, a system state.
 * Between them they say "this reads your company's records" more directly
 * than a sentence claiming it would.
 */
const EXAMPLE_QUESTIONS = [
  'How do I request production access?',
  'What changed in our security policy?',
  'Show me our onboarding process.',
  'Summarise the latest incident report.',
  'Which connector is failing?',
]

/**
 * Ask Arc — Unified Intelligence.
 *
 * This is the product-facing surface for ARC's core differentiator.
 * The backend Unified Intelligence / chat contract now exists:
 * POST /tenants/{tenant_id}/intelligence/query
 */

/**
 * What went wrong, in terms the reader can act on.
 *
 * Three outcomes are worth telling apart: they cannot do this, the network
 * is down, or the request failed. Anything finer is the server's own
 * message, which is for logs and observability — not for the person who
 * asked a question.
 */
function askErrorTitle(error) {
  const api = toApiError(error)
  if (api.isForbidden) return "You don't have access to ask questions here."
  if (api.isNetwork) return "Can't reach Arc."
  return "That question couldn't be answered."
}

function askErrorHelp(error) {
  const api = toApiError(error)
  if (api.isForbidden) return 'Ask your workspace administrator for access to Company Brain.'
  if (api.isNetwork) return 'Check your connection and try again.'
  return 'Something went wrong on our side. Try asking again.'
}

export function AskArcPage() {
  const { tenantId } = useTenant()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [error, setError] = useState(null)
  const [source, setSource] = useState('')
  const sources = answer ? parseCitations(answer.citations, tenantId) : []

  // What Arc can actually search, for the empty state's rail.
  const knowledge = useQuery({
    queryKey: queryKeys.knowledge(tenantId),
    queryFn: () => getKnowledge(tenantId),
    enabled: Boolean(tenantId),
  })
  const corpus = Array.isArray(knowledge.data)
    ? knowledge.data
    : (knowledge.data?.items ?? [])
  const lastSubmitRef = useRef(0)
  const [touched, setTouched] = useState(false)

  const mutation = useMutation({
    mutationFn: (payload) => queryIntelligence(tenantId, payload),
    onSuccess: (data) => {
      setAnswer(data)
      setError(null)
    },
    onError: (err) => {
      setError(err)
      setAnswer(null)
    },
  })

  // The ghost runs only while the field is genuinely untouched and idle.
  const showGhost = !question && !touched && !answer && !error && !mutation.isPending
  const ghost = useTypewriter(EXAMPLE_QUESTIONS, showGhost)

  const handleCopy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Clipboard API may fail in insecure contexts or when permissions
      // are denied. The user can still manually select and copy the text.
    }
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!question.trim()) return
    const now = Date.now()
    if (now - lastSubmitRef.current < 1000) return
    lastSubmitRef.current = now
    // The branch is load-bearing: source_type: "" would 422 against
    // Optional[KnowledgeSource], so the key is omitted when unscoped.
    mutation.mutate(
      source ? { query: question.trim(), limit: 5, source_type: source } : { query: question.trim(), limit: 5 },
    )
  }

  const handleClear = () => {
    setTouched(false)
    setQuestion('')
    setAnswer(null)
    setError(null)
    // source intentionally persists: it is a scope preference, not
    // per-question state, like a selected tab rather than a draft.
  }

  const asked = mutation.isPending || answer || error

  return (
    /* Asymmetric by design: the answer takes the field, its sources take a
       margin. Sources ARE marginalia — you read the answer, and you glance
       right to check where it came from. Putting them below would make
       provenance a footnote you scroll to, which is the opposite of what
       ADR-008 makes the product about. */
    <div
      className={cn(
        'grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,1fr)_17rem]',
        !asked && 'lg:min-h-[58vh] lg:items-center',
      )}
    >
      <div className="min-w-0">
        {/* The question is the page subject. It is not a label above a
            field — when it has been asked, it IS the headline, set at
            display size, and the answer follows it like body copy under a
            title. Before it is asked, the prompt takes that position so
            the composition does not jump. */}
        <form onSubmit={handleSubmit} className="relative">
          <label htmlFor="arc-question" className="type-label text-fg-muted">
            Ask Arc
          </label>
          <div className="relative mt-3">
            <textarea
            id="arc-question"
            value={question}
            onChange={(event) => {
              setTouched(true)
              setQuestion(event.target.value)
              setAnswer(null)
              setError(null)
            }}
            onKeyDown={(event) => {
              // Enter sends; Shift+Enter breaks the line. A question is
              // usually one line, and reaching for a button to send it is
              // friction on the one surface that should feel immediate.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                handleSubmit(event)
              }
            }}
            rows={2}
            disabled={mutation.isPending}
            onFocus={() => setTouched(true)}
            aria-describedby={showGhost ? 'arc-question-ghost' : undefined}
            className={cn(
              'type-display-lg relative z-10 block w-full resize-none bg-transparent text-fg',
              'focus-visible:outline-none disabled:opacity-60',
            )}
          />

          {/* The ghost sits under the real field rather than in its
              placeholder attribute, because a placeholder cannot carry a
              caret and cannot animate. It is aria-hidden: a screen reader
              gets the label, not a string mutating letter by letter. The
              textarea above is transparent, so the two share one box. */}
          {showGhost && (
            <p
              id="arc-question-ghost"
              aria-hidden
              className="type-display-lg pointer-events-none absolute inset-x-0 top-0 select-none text-fg-muted/55"
            >
              {ghost.text}
              {!ghost.done && (
                <span className="ml-0.5 inline-block h-[0.9em] w-px animate-pulse bg-accent align-[-0.08em] motion-reduce:animate-none" />
              )}
            </p>
          )}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <Select
              label="Sources"
              id="arc-source"
              value={source}
              onChange={(event) => {
                setSource(event.target.value)
                // The scope describes the displayed answer: changing it
                // clears a stale answer rather than misdescribing it.
                setAnswer(null)
                setError(null)
              }}
              disabled={mutation.isPending}
            >
              <option value="">All sources</option>
              {Object.keys(sourceLabels).map((name) => (
                <option key={name} value={name}>
                  {sourceLabels[name] ?? name}
                </option>
              ))}
            </Select>
            <Button type="submit" disabled={!question.trim() || mutation.isPending} isLoading={mutation.isPending} loadingText="Reading the record…">
              <Sparkles className="size-4" />
              Ask
            </Button>
            {(answer || error || question.trim()) && (
              <Button type="button" variant="ghost" size="sm" onClick={handleClear} disabled={mutation.isPending}>
                <RotateCcw className="size-3.5" />
                Clear
              </Button>
            )}
            <p className="ml-auto hidden text-xs text-fg-muted sm:block">
              Enter to ask · Shift + Enter for a new line
            </p>
          </div>
        </form>

        {mutation.isPending && (
          <div className="mt-10 flex items-center gap-3 text-[15px] text-fg-muted">
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
            <p>Retrieving authorised company knowledge…</p>
          </div>
        )}

        {error && (
          <div className="mt-10">
            <InlineError>
              {/* Deliberately not errorMessage(error): that returns the
                  backend's own `detail`, which on a 500 is whatever the
                  server said. ARC_UX_SPEC.md §1 rules out raw API errors,
                  and the primary product surface is the last place to
                  leak one. */}
              <p className="font-medium text-fg">{askErrorTitle(error)}</p>
              <p className="mt-1">{askErrorHelp(error)}</p>
            </InlineError>
          </div>
        )}

        {answer && (
          <section className="mt-10" aria-live="polite">
            {answer.answer ? (
              /* The answer is prose, so it is set as prose: display serif,
                 17px, 1.65 line-height, capped at a reading measure. This
                 is the one place in Arc where the type is doing the work
                 of the product. */
              <div className="type-prose measure animate-rise whitespace-pre-wrap text-fg">
                {answer.answer}
              </div>
            ) : (
              <div className="measure">
                <p className="type-prose text-fg">
                  Nothing in your Company Brain covers this yet.
                </p>
                <p className="mt-2 text-[15px] leading-relaxed text-fg-muted">
                  Arc answers only from your company&apos;s own knowledge. It
                  will not fill the gap from somewhere else.
                </p>
              </div>
            )}

            <p className="mt-8 border-t border-line pt-4 text-[13px] text-fg-muted">
              {groundingSummary(answer, tenantId)}
              {answer.request_id && (
                <>
                  {' · '}
                  <button
                    type="button"
                    onClick={() => handleCopy(answer.request_id)}
                    className="underline underline-offset-2 transition-colors hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  >
                    Copy reference
                  </button>
                </>
              )}
            </p>
          </section>
        )}

      </div>

      {/* The margin. Empty until there is provenance to show — an empty
          rail is better than a rail full of placeholder. */}
      <aside className="min-w-0 lg:pt-9">
        {sources.length > 0 ? (
          <>
            <h2 className="type-label text-fg-muted">
              Sources · {sources.length}
            </h2>
            <ol className="stagger mt-3 border-t border-line">
              {sources.map((source, index) => (
                <li key={source.documentId}>
                  <Link
                    to={`../knowledge/${encodeURIComponent(source.documentId)}`}
                    className={cn(
                      'group flex gap-3 border-b border-line py-3',
                      'transition-colors duration-150 hover:bg-surface-sunk/60',
                      'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary',
                    )}
                  >
                    <span className="type-data pt-0.5 text-fg-muted">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span className="min-w-0 flex-1 text-[13.5px] leading-snug text-fg-subtle group-hover:text-fg">
                      {source.label}
                    </span>
                    <ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-fg-muted transition-colors group-hover:text-fg" />
                  </Link>
                </li>
              ))}
            </ol>
          </>
        ) : (
          !asked && (
            /* Before a question is asked, this rail says what Arc can
               search — the actual documents, not a sentence claiming it
               reads your knowledge. It answers the question a person
               genuinely has on an empty Ask Arc ("what can I ask about?")
               with real records, and it is the same column that holds the
               sources afterwards. */
            <>
              <h2 className="type-label text-fg-muted">
                Arc is reading
                {corpus.length > 0 && ` · ${corpus.length}`}
              </h2>
              {knowledge.isPending ? (
                <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-4 w-32" />
                </div>
              ) : corpus.length === 0 ? (
                <p className="measure-tight mt-3 border-t border-line pt-3 text-[13.5px] leading-relaxed text-fg-muted">
                  Nothing in the Company Brain yet. Arc answers only from your
                  company&apos;s own knowledge, so it has nothing to draw on.
                </p>
              ) : (
                <>
                  <ul className="mt-3 border-t border-line">
                    {corpus.slice(0, 5).map((doc) => (
                      <li key={doc.id}>
                        <Link
                          to={`../knowledge/${encodeURIComponent(doc.id)}`}
                          className="block truncate border-b border-line py-2.5 text-[13.5px] text-fg-subtle transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"
                        >
                          {documentTitle(doc)}
                        </Link>
                      </li>
                    ))}
                  </ul>
                  <p className="measure-tight mt-3 text-[12.5px] leading-relaxed text-fg-muted">
                    {corpus.length > 5 && `and ${corpus.length - 5} more. `}
                    Arc never answers from outside these.
                  </p>
                </>
              )}
            </>
          )
        )}
      </aside>
    </div>
  )
}
