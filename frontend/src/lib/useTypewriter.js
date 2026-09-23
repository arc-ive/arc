import { useEffect, useRef, useState } from 'react'

/**
 * A question typing itself into the empty Ask Arc field.
 *
 * The empty state was a placeholder and a list of four links — correct, and
 * completely inert on the one surface that is the product's reason to
 * exist. A question assembling itself in the field shows what Arc is for
 * faster than a sentence explaining it, and it shows the *kind* of question
 * that works here, which the examples list was trying to do statically.
 *
 * Rules it follows, so it stays a product detail rather than a gimmick:
 *
 *  - It stops the instant the field is touched. `active` goes false on
 *    focus or on the first keystroke and never resumes, because a caret
 *    racing a user's own typing is the failure mode of this pattern.
 *  - Deleting runs faster than typing. Reversing an animation at its
 *    entry speed reads as slow; exits should be quicker than entrances.
 *  - Under `prefers-reduced-motion` it does not animate at all — it
 *    returns the first question, whole, and stops. Not a slower
 *    animation: none.
 *
 * Timings are in the range where typing reads as deliberate rather than
 * frantic: ~26ms a character in, ~12ms out, a beat to read at the end.
 */
const TYPE_MS = 26
const DELETE_MS = 12
const HOLD_MS = 1900
const BETWEEN_MS = 320

export function useTypewriter(phrases, active = true) {
  // Read once, in a state initialiser rather than a ref, so it is settled
  // before the first render instead of being reached for during one. A
  // user who changes the setting mid-session gets the new behaviour on the
  // next navigation, which is soon enough for a decoration and cheaper
  // than holding a media-query listener open for one.
  const [reduced] = useState(
    () =>
      typeof window !== 'undefined' &&
      Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches),
  )

  const [text, setText] = useState('')
  const timer = useRef(null)

  useEffect(() => {
    if (reduced || !active || phrases.length === 0) return undefined

    let index = 0
    let chars = 0
    let deleting = false
    let cancelled = false

    const step = () => {
      if (cancelled) return
      const phrase = phrases[index]

      if (!deleting) {
        chars += 1
        setText(phrase.slice(0, chars))
        if (chars === phrase.length) {
          deleting = true
          timer.current = setTimeout(step, HOLD_MS)
          return
        }
        timer.current = setTimeout(step, TYPE_MS)
        return
      }

      chars -= 1
      setText(phrase.slice(0, chars))
      if (chars === 0) {
        deleting = false
        index = (index + 1) % phrases.length
        timer.current = setTimeout(step, BETWEEN_MS)
        return
      }
      timer.current = setTimeout(step, DELETE_MS)
    }

    timer.current = setTimeout(step, 420)
    return () => {
      cancelled = true
      clearTimeout(timer.current)
    }
  }, [phrases, active, reduced])

  // Under reduced motion the whole first question is returned at once and
  // `done` hides the caret — not a slower animation, none.
  if (reduced) return { text: phrases[0] ?? '', done: true }

  // Deriving the empty string rather than setting state on deactivate:
  // the effect's cleanup stops the timer, but the last partial phrase
  // would otherwise stay in state and the caller would be handed a frozen
  // half-question. Derived, so there is no setState in an effect either.
  return { text: active ? text : '', done: false }
}
