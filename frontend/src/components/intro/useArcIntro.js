import { useCallback, useState } from 'react'

const SEEN_KEY = 'arc.intro.seen'

/**
 * Whether the entrance should play.
 *
 * It plays once per browser session, after a sign-in. Not on every route
 * change, not on a refresh of an already-open session — an animation a
 * person sees forty times a day is an obstacle, however good it is.
 *
 * Three ways it never plays:
 *
 *  - `prefers-reduced-motion`. Skipped outright rather than slowed. A
 *    warp toward the viewer is exactly the kind of motion that setting
 *    exists to prevent.
 *  - Already seen this session.
 *  - `sessionStorage` unavailable (private mode, blocked site data). The
 *    read is wrapped, and the fallback is not to play: a decoration
 *    should fail closed.
 *
 * The decision is made when authentication BECOMES true, not once at
 * mount. `RequireAuth` renders first while the session is still being
 * checked, so at mount `isAuthenticated` is false in every real sign-in
 * — a `useState` initializer reading it there latches "skip" forever and
 * the entrance never runs. The transition is what matters, so it is
 * handled by adjusting state during render (React's documented
 * alternative to an effect) rather than in an effect, which would fire a
 * render late and set state needlessly.
 */
export function useArcIntro(isAuthenticated) {
  const [phase, setPhase] = useState(() => (isAuthenticated ? decide() : 'skipped'))
  const [wasAuthenticated, setWasAuthenticated] = useState(isAuthenticated)

  if (isAuthenticated !== wasAuthenticated) {
    setWasAuthenticated(isAuthenticated)
    // Decide on the rising edge only. Losing authentication resets the
    // edge detector but does not re-open the curtain: a session that
    // expires mid-visit should not be answered with an animation.
    if (isAuthenticated) setPhase(decide())
  }

  const finish = useCallback(() => {
    try {
      sessionStorage.setItem(SEEN_KEY, '1')
    } catch {
      // Storage can throw outright, not just return null. If it does, the
      // intro simply plays again next sign-in, which is harmless.
    }
    setPhase('skipped')
  }, [])

  return { showIntro: phase === 'playing', onIntroDone: finish }
}

function decide() {
  if (typeof window === 'undefined') return 'skipped'

  try {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 'skipped'
  } catch {
    return 'skipped'
  }

  try {
    return sessionStorage.getItem(SEEN_KEY) === '1' ? 'skipped' : 'playing'
  } catch {
    return 'skipped'
  }
}

/**
 * Forget that the entrance has played.
 *
 * Called on sign-out. `sessionStorage` is per-tab and survives the
 * full-page navigation `signOut` performs, so without this the next
 * person to sign in on that tab — a different person, on a shared or
 * demo machine — would be met with no entrance at all. Sign-out ends the
 * session the flag describes, so the flag goes with it.
 */
export function clearArcIntroSeen() {
  try {
    sessionStorage.removeItem(SEEN_KEY)
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}
