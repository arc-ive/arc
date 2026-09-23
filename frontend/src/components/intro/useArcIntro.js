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
 */
export function useArcIntro(isAuthenticated) {
  const [done, setDone] = useState(() => !shouldPlay(isAuthenticated))

  const finish = useCallback(() => {
    try {
      sessionStorage.setItem(SEEN_KEY, '1')
    } catch {
      // Storage can throw outright, not just return null. If it does, the
      // intro simply plays again next sign-in, which is harmless.
    }
    setDone(true)
  }, [])

  return { showIntro: !done, onIntroDone: finish }
}

function shouldPlay(isAuthenticated) {
  if (!isAuthenticated) return false
  if (typeof window === 'undefined') return false

  try {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false
  } catch {
    return false
  }

  try {
    return sessionStorage.getItem(SEEN_KEY) !== '1'
  } catch {
    return false
  }
}

/** Exposed for tests and for sign-out, which should let it play again. */
export function clearArcIntroSeen() {
  try {
    sessionStorage.removeItem(SEEN_KEY)
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}
