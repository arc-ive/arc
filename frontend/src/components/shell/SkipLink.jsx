export const MAIN_CONTENT_ID = 'main-content'

/**
 * The first thing a keyboard user reaches.
 *
 * Measured before this existed: 20 tab stops separated the top of the
 * document from the first control inside `<main>` — the whole sidebar and
 * top bar, on every page, every time. Someone navigating by keyboard paid
 * that cost on each route change.
 *
 * It is visually hidden until focused, which is why it is clipped rather
 * than hidden: `display: none` and `visibility: hidden` both remove an
 * element from the focus order, so the link would never be reachable.
 *
 * The click is handled rather than left to the browser. A bare
 * `href="#main-content"` did nothing here — verified in the browser, the
 * fragment never applied (`location.hash` stayed empty) and the next Tab
 * went straight back to the first sidebar link, so the link looked right
 * and skipped nothing. Moving focus explicitly does not depend on how the
 * router treats a fragment.
 */
export function SkipLink() {
  const handleActivate = (event) => {
    const main = document.getElementById(MAIN_CONTENT_ID)
    if (!main) return
    event.preventDefault()
    main.focus()
    main.scrollTo?.({ top: 0 })
  }

  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      onClick={handleActivate}
      className="sr-only rounded-lg border border-line bg-panel px-4 py-2 text-sm font-medium text-fg shadow-card focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
    >
      Skip to content
    </a>
  )
}
