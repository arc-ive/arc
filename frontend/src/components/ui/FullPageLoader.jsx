import { Spinner } from './Spinner.jsx'

/**
 * The whole-screen wait.
 *
 * Three routes — the auth gate, the platform-admin gate and login — each
 * hand-rolled the same block: a bordered div with `animate-spin`, using
 * `border-zinc-600`, a value the token system does not define.
 *
 * They also said nothing. `Spinner` is `aria-hidden` (correct: a spinning
 * ring is decoration), so these screens presented as empty to a screen
 * reader — no heading, no text, no status. These are the first screens a
 * user meets, and the one moment where "wait" is the entire message.
 */
export function FullPageLoader({ label = 'Loading' }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-dvh items-center justify-center bg-base"
    >
      <Spinner className="size-6 text-fg-muted" />
      <span className="sr-only">{label}</span>
    </div>
  )
}
