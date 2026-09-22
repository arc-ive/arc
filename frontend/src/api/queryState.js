/**
 * Shared query-phase resolution (Issue #225).
 *
 * React Query reports a query that has failed and is waiting to retry as
 * `status: 'pending'` with `fetchStatus: 'paused'`. A page that renders a
 * skeleton whenever `isPending` is true therefore shows a loading state
 * that never resolves and never reports an error — the request failed,
 * but the user cannot perceive it.
 *
 * `queryPhase` collapses the React Query flags into the four states a
 * page actually renders, so every surface makes the same decision:
 *
 *   'loading'  a request is genuinely in flight and has no result yet
 *   'error'    the request failed and the error is available
 *   'stalled'  the request failed and is parked, unable to proceed
 *   'ready'    data is available (the page renders success or empty)
 *
 * `'stalled'` is surfaced as an error state rather than as loading:
 * a request that cannot proceed is a failure the user must be able to
 * see and retry, not an indefinite wait.
 */

export const QUERY_PHASE = Object.freeze({
  LOADING: 'loading',
  ERROR: 'error',
  STALLED: 'stalled',
  READY: 'ready',
})

export function queryPhase(query) {
  if (!query) return QUERY_PHASE.LOADING
  if (query.isError) return QUERY_PHASE.ERROR
  // A pending query that is not fetching cannot make progress on its own.
  if (query.isPending && query.fetchStatus === 'paused') return QUERY_PHASE.STALLED
  if (query.isPending) return QUERY_PHASE.LOADING
  return QUERY_PHASE.READY
}

/** True when the page should render a loading skeleton. */
export function isQueryLoading(query) {
  return queryPhase(query) === QUERY_PHASE.LOADING
}

/** True when the page must show a failure the user can act on. */
export function isQueryFailed(query) {
  const phase = queryPhase(query)
  return phase === QUERY_PHASE.ERROR || phase === QUERY_PHASE.STALLED
}

/** Message for a query that failed without producing an error object. */
export const STALLED_MESSAGE =
  'The request could not be completed. Check your connection and try again.'
