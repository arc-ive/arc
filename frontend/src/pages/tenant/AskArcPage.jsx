import { useState, useRef } from 'react'
import { InlineError } from '../../components/ui/InlineError.jsx'
import { PageHeader } from '../../components/ui/PageHeader.jsx'
import { useMutation } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Loader2,
  Sparkles,
  RotateCcw,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardContent } from '../../components/ui/Card.jsx'
import { parseCitations, groundingSummary } from '../../lib/citations.js'
import { Button } from '../../components/ui/Button.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { useTenant } from '../../tenant/useTenant.js'
import { queryIntelligence } from '../../api/endpoints/intelligence.js'
import { toApiError } from '../../api/errors.js'

const EXAMPLE_QUESTIONS = [
  'How do I request production access?',
  'What is our leave policy?',
  'What is the procedure for recovering a locked account?',
  'Show me the approved process for X.',
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
  const sources = answer ? parseCitations(answer.citations, tenantId) : []
  const lastSubmitRef = useRef(0)

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
    mutation.mutate({ query: question.trim(), limit: 5 })
  }

  const handleExampleClick = (example) => {
    setQuestion(example)
    setAnswer(null)
    setError(null)
  }

  const handleClear = () => {
    setQuestion('')
    setAnswer(null)
    setError(null)
  }

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <PageHeader title="Ask Arc"
          description="Answers grounded in your company's own knowledge, with the documents they came from." />
          </div>
        </div>
      </section>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-3 rounded-xl border border-line/80 bg-panel p-5 shadow-card"
      >
        <Textarea
          label="Ask anything about your company"
          placeholder="e.g. How do I request production access?"
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value)
            setAnswer(null)
            setError(null)
          }}
          rows={4}
          disabled={mutation.isPending}
        />
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
          </div>
          <div className="flex items-center gap-2">
            {(answer || error || question.trim()) && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleClear}
                disabled={mutation.isPending}
              >
                <RotateCcw className="size-3.5" />
                Clear
              </Button>
            )}
            <Button type="submit" disabled={!question.trim() || mutation.isPending} isLoading={mutation.isPending} loadingText="Thinking…">
              <Sparkles className="size-4" />
              Ask
            </Button>
          </div>
        </div>
      </form>

      {mutation.isPending && (
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3.5 py-3 text-[13px] text-amber-200/80">
          <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin motion-reduce:animate-none" />
          <p>
            Retrieving authorized company knowledge and reasoning…
          </p>
        </div>
      )}

      {error && (
        <InlineError>
          {/* Deliberately not errorMessage(error): that returns the
              backend's own `detail`, which on a 500 is whatever the server
              said ("Internal Server Error", "boom"). ARC_UX_SPEC.md §1
              rules out raw API errors, and the primary product surface is
              the last place to leak one. Permission and connectivity are
              distinguished because a reader can act on those; everything
              else is "try again". */}
          <p className="font-medium text-fg">{askErrorTitle(error)}</p>
          <p className="mt-1">{askErrorHelp(error)}</p>
        </InlineError>
      )}

      {answer && (
        <section className="flex flex-col gap-4" aria-live="polite">
          <Card className="overflow-hidden">
            <CardContent className="py-6">
              {answer.answer ? (
                <div className="whitespace-pre-wrap text-[15px] leading-relaxed text-fg">
                  {answer.answer}
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <p className="text-[15px] font-medium text-fg">
                    No grounded answer for this question.
                  </p>
                  <p className="text-[13px] leading-relaxed text-fg-muted">
                    Nothing in your Company Brain covers it yet. Arc will not
                    answer from outside your company&apos;s own knowledge.
                  </p>
                </div>
              )}
            </CardContent>

            <div className="border-t border-line px-5 py-3">
              <p className="text-[13px] text-fg-muted">{groundingSummary(answer, tenantId)}</p>
            </div>
          </Card>

          {sources.length > 0 && (
            <section>
              <h2 className="mb-2 text-[13px] font-semibold text-fg">
                Sources
              </h2>
              <ol className="flex flex-col gap-1.5">
                {sources.map((source, index) => (
                  <li key={source.documentId}>
                    <Link
                      to={`../knowledge/${encodeURIComponent(source.documentId)}`}
                      className="group flex items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-2.5 transition-colors duration-150 hover:border-line-strong hover:bg-surface-raised focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                    >
                      <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                        [{index + 1}]
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg">
                        {source.label}
                      </span>
                      <ArrowUpRight className="size-3.5 shrink-0 text-fg-muted transition-colors group-hover:text-fg" />
                    </Link>
                  </li>
                ))}
              </ol>
            </section>
          )}

          {answer.request_id && (
            <p className="text-xs text-fg-muted">
              Something wrong with this answer?{' '}
              <button
                type="button"
                onClick={() => handleCopy(answer.request_id)}
                className="underline underline-offset-2 transition-colors hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                Copy the reference
              </button>{' '}
              to include when you report it.
            </p>
          )}
        </section>
      )}

      {!mutation.isPending && !answer && !error && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-fg">
            Example questions
          </h2>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => handleExampleClick(example)}
                disabled={mutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface-raised px-3 py-1.5 text-[13px] text-fg-muted transition-colors duration-150 hover:border-line-strong hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ArrowUpRight className="size-3.5" />
                {example}
              </button>
            ))}
          </div>
        </section>
      )}

      {!answer && !mutation.isPending && (
        <p className="max-w-[70ch] text-[13px] leading-relaxed text-fg-muted">
          Arc answers from your company&apos;s own knowledge and shows the
          documents it used. It never answers from outside them.
        </p>
      )}
    </div>
  )
}
