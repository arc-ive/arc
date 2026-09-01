import { useState, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  ArrowUpRight,
  BookOpen,
  FileSearch,
  Loader2,
  Sparkles,
  Workflow,
  Wrench,
  Copy,
  CircleAlert,
  ShieldCheck,
  RotateCcw,
} from 'lucide-react'
import { Badge } from '../../components/ui/Badge.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'
import { useAuth } from '../../auth/useAuth.js'
import { useTenant } from '../../tenant/useTenant.js'
import { queryIntelligence } from '../../api/endpoints/intelligence.js'
import { errorMessage } from '../../api/errors.js'

const EXAMPLE_QUESTIONS = [
  'How do I request production access?',
  'What is our leave policy?',
  'What is the procedure for recovering a locked account?',
  'Show me the approved process for X.',
]

const PIPELINE_STEPS = [
  {
    icon: FileSearch,
    title: 'Retrieve',
    description:
      'Arc searches the tenant\'s Company Brain — policies, procedures, decisions, incidents, and solutions — for context it is authorized to use.',
  },
  {
    icon: ShieldCheck,
    title: 'Reason',
    description:
      'Unified Intelligence answers from retrieved company knowledge with source and provenance, never from unsanctioned context.',
  },
  {
    icon: Workflow,
    title: 'Apply skills',
    description:
      'Approved procedures are applied as structured skills when the question matches an authorized workflow.',
  },
  {
    icon: Wrench,
    title: 'Execute permitted tools',
    description:
      'If an action is required, only tools the user is permitted to execute are offered, with visible execution status.',
  },
  {
    icon: CircleAlert,
    title: 'Verify and escalate',
    description:
      'High-risk actions require human approval; failed or sensitive situations escalate to the operations team.',
  },
]

/**
 * Ask Arc — Unified Intelligence.
 *
 * This is the product-facing surface for ARC's core differentiator.
 * The backend Unified Intelligence / chat contract now exists:
 * POST /tenants/{tenant_id}/intelligence/query
 */
export function AskArcPage() {
  const { isDemo } = useAuth()
  const { tenantId } = useTenant()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [error, setError] = useState(null)
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
          <div className="flex size-10 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-zinc-400">
            <Sparkles className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              Ask Arc
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Company-aware answers grounded in the Company Brain, with
              sources, skills, and permitted actions.
            </p>
          </div>
        </div>
      </section>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-3 rounded-xl border border-zinc-800/80 bg-panel p-5 shadow-card"
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
            {isDemo && (
              <>
                <Badge variant="amber" dot size="sm">
                  Demo Mode
                </Badge>
                <span className="hidden text-xs text-zinc-600 sm:inline">
                  No backend session in Demo Mode.
                </span>
              </>
            )}
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
            <Button type="submit" disabled={!question.trim() || mutation.isPending || isDemo} isLoading={mutation.isPending} loadingText="Thinking…">
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
        <div className="rounded-lg border border-red-900/50 bg-red-950/20 px-3.5 py-3 text-[13px] text-red-300">
          <p className="font-semibold">Error:</p>
          <p className="mt-1">{errorMessage(error)}</p>
        </div>
      )}

      {answer && (
        <Card className="overflow-hidden">
          <CardHeader
            title="Answer"
            description={answer.request_id ? `Request: ${answer.request_id}` : undefined}
          />
          <CardContent className="py-5">
            {answer.answer ? (
              <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-zinc-300">
                {answer.answer}
              </div>
            ) : (
              <p className="text-sm text-zinc-500">
                No answer could be generated from the available knowledge.
              </p>
            )}
          </CardContent>

          {(answer.citations?.length ?? 0) > 0 && (
            <div className="border-t border-zinc-800/70 px-5 py-4">
              <h3 className="text-sm font-semibold text-zinc-200 mb-3">
                Sources & Provenance
              </h3>
              <div className="flex flex-col gap-2">
                {answer.citations.map((citation, idx) => (
                  <div
                    key={idx}
                    className="rounded-lg border border-zinc-800/70 bg-zinc-900/40 p-3 text-sm text-zinc-300"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-zinc-500">
                        [{idx + 1}]
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleCopy(citation)}
                        className="h-6 px-2"
                      >
                        <Copy className="size-3.5" />
                      </Button>
                    </div>
                    <p className="mt-1 font-mono text-[11px] leading-relaxed">{citation}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="border-t border-zinc-800/70 px-5 py-4 text-xs text-zinc-500">
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              <div>
                <dt>Retrieval method</dt>
                <dd className="font-mono">{answer.retrieval_method}</dd>
              </div>
              <div>
                <dt>Context used</dt>
                <dd className="font-mono">{answer.context_used ? 'Yes' : 'No'}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt>Principal</dt>
                <dd className="font-mono truncate">{answer.principal_id}</dd>
              </div>
            </dl>
          </div>
        </Card>
      )}

      {!mutation.isPending && !answer && !error && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-zinc-200">
            Example questions
          </h2>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => handleExampleClick(example)}
                disabled={mutation.isPending || isDemo}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-1.5 text-[13px] text-zinc-400 transition-colors duration-150 hover:border-zinc-700 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ArrowUpRight className="size-3.5" />
                {example}
              </button>
            ))}
          </div>
        </section>
      )}

      <Card>
        <CardHeader
          title="How Arc answers"
          description="Unified Intelligence pipeline — company-aware, sourced, and controlled."
        />
        <CardContent>
          <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {PIPELINE_STEPS.map((step, index) => (
              <li
                key={step.title}
                className="flex flex-col gap-2.5 rounded-lg border border-zinc-800/70 bg-zinc-900/40 p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="flex size-8 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-indigo-400">
                    <step.icon className="size-4" />
                  </div>
                  <span className="font-mono text-[11px] text-zinc-600">
                    0{index + 1}
                  </span>
                </div>
                <p className="text-[13px] font-semibold text-zinc-100">
                  {step.title}
                </p>
                <p className="text-xs leading-relaxed text-zinc-500">
                  {step.description}
                </p>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="What an answer includes"
          description="The response surface Arc renders for Unified Intelligence queries."
        />
        <CardContent>
          <div className="flex flex-col gap-3">
            <div className="flex items-start gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-4 py-3">
              <BookOpen className="mt-0.5 size-4 shrink-0 text-zinc-500" />
              <div>
                <p className="text-[13px] font-semibold text-zinc-200">
                  Sources & provenance
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                  Every claim links to the Company Brain documents it came
                  from — policy, procedure, incident, or solution — with
                  version and provenance.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-4 py-3">
              <Workflow className="mt-0.5 size-4 shrink-0 text-zinc-500" />
              <div>
                <p className="text-[13px] font-semibold text-zinc-200">
                  Skill & tool execution
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                  Approved procedures appear as selectable skills; permitted
                  actions show live execution status (requested, running,
                  completed, failed).
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-4 py-3">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-zinc-500" />
              <div>
                <p className="text-[13px] font-semibold text-zinc-200">
                  Human approval & escalation
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                  High-risk actions present an explicit Approve / Reject
                  decision; escalation routes to the operations team when
                  required. Internal chain-of-thought is never exposed.
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}