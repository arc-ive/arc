import { useEffect } from 'react'

/**
 * Name the document after the page.
 *
 * Every route shipped as "Arc". That is the title in the browser tab, in
 * the history menu, in a bookmark, in the window switcher — and it is what
 * a screen reader announces on navigation, which in a single-page app is
 * the main signal that navigation happened at all. Every route named
 * identically means none of those can tell you where you are.
 */
export const APP_NAME = 'Arc'

export function documentTitleFor(title) {
  const page = String(title ?? '').trim()
  if (!page || page === APP_NAME) return APP_NAME
  return `${page} · ${APP_NAME}`
}

export function useDocumentTitle(title) {
  useEffect(() => {
    if (!title) return undefined
    const previous = document.title
    document.title = documentTitleFor(title)
    // Restoring on unmount keeps a transient surface — a detail page
    // opened and closed, a route that unmounts behind a dialog — from
    // leaving its name behind on the page that follows it.
    return () => {
      document.title = previous
    }
  }, [title])
}
