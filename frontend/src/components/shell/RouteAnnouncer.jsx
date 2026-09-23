import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Say the page name when the route changes.
 *
 * In a single-page app, navigation replaces the content without a document
 * load, so a screen reader is given nothing to announce — the user
 * activates a link and hears silence, with no confirmation that anything
 * happened. `document.title` alone is not reliably announced on an SPA
 * route change; a polite live region is.
 *
 * It reads the title that PageHeader has just set, so the announcement and
 * the <h1> cannot disagree.
 */
export function RouteAnnouncer() {
  const { pathname } = useLocation()
  const [message, setMessage] = useState('')
  const firstRender = useRef(true)

  useEffect(() => {
    // The initial load is a real document load, which the browser already
    // announces. Announcing it again would double up.
    if (firstRender.current) {
      firstRender.current = false
      return undefined
    }

    // The title is set by the incoming page's own PageHeader effect, which
    // runs after this one. A frame's delay lets it land first; without it
    // the announcement names the page being left.
    const timer = setTimeout(() => {
      setMessage(document.title)
    }, 100)

    return () => clearTimeout(timer)
  }, [pathname])

  return (
    <div aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </div>
  )
}
