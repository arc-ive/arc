import { useState } from 'react'
import {
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  CircleAlert,
  FileSearch,
  Loader2,
  ShieldCheck,
  Sparkles,
  Workflow,
  Wrench,
} from 'lucide-react'
import { Badge } from '../../components/ui/Badge.jsx'
import { Card, CardContent, CardHeader } from '../../components/ui/Card.jsx'
import { Button } from '../../components/ui/Button.jsx'
import { Textarea } from '../../components/ui/Textarea.jsx'

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
      'Arc searches the tenant’s Company Brain — policies, procedures, decisions, incidents, and solutions — for context it is authorized to use.',
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
 * This is the product-facing surface for ARC's core differentiator. The
 * backend Unified Intelligence / chat contract does not exist yet, so this
 * surface is not wired to any API: the composer is real, but submissions
 * are not fabricated and no fake answer is generated.
 */
export function AskArcPage() {
  const [question, setQuestion] = useState('')
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!question.trim()) return
    setSubmitted(true)
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
            setSubmitted(false)
          }}
          rows={4}
        />
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="amber" dot size="sm">
              Contract pending
            </Badge>
            <span className="hidden text-xs text-zinc-600 sm:inline">
              The Unified Intelligence API has not been implemented yet.
            </span>
          </div>
          <Button type="submit" disabled={!question.trim()}>
            <Sparkles className="size-4" />
            Ask
          </Button>
        </div>
        {submitted && (
          <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3.5 py-3 text-[13px] text-amber-200/80">
            <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin motion-reduce:animate-none" />
            <p>
              This question would be routed to Arc’s Unified Intelligence —
              retrieving authorized company knowledge, selecting applicable
              skills, and surfacing sources. The backend contract does not
              exist yet, so no answer is fabricated.
            </p>
          </div>
        )}
      </form>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-zinc-200">
          Example questions
        </h2>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setQuestion(example)
                setSubmitted(false)
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-1.5 text-[13px] text-zinc-400 transition-colors duration-150 hover:border-zinc-700 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
            >
              <ArrowUpRight className="size-3.5" />
              {example}
            </button>
          ))}
        </div>
      </section>

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
          description="The response surface Arc will render once the backend contract exists."
        />
        <CardContent>
          <div className="flex flex-col gap-3">
            <div className="flex items-start gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-4 py-3">
              <BookOpen className="mt-0.5 size-4 shrink-0 text-zinc-500" />
              <div>
                <p className="text-[13px] font-semibold text-zinc-200">
                  Sources &amp; provenance
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
                  Skill &amp; tool execution
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                  Approved procedures appear as selectable skills; permitted
                  actions show live execution status (requested, running,
                  completed, failed).
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-zinc-800/70 bg-zinc-900/40 px-4 py-3">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-zinc-500" />
              <div>
                <p className="text-[13px] font-semibold text-zinc-200">
                  Human approval &amp; escalation
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