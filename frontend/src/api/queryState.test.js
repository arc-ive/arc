import { describe, it, expect } from 'vitest'
import {
  QUERY_PHASE,
  isQueryFailed,
  isQueryLoading,
  queryPhase,
} from './queryState.js'

/**
 * Issue #225. The bug was not a missing error branch — it was that a
 * query which has failed and parked reports `status: 'pending'`, so
 * `if (isPending) return <Skeleton/>` renders forever. These tests pin
 * the classification that makes the four states distinct.
 */
describe('queryPhase', () => {
  const loading = { isPending: true, isError: false, fetchStatus: 'fetching' }
  const stalled = { isPending: true, isError: false, fetchStatus: 'paused' }
  const errored = { isPending: false, isError: true, fetchStatus: 'idle', error: new Error('x') }
  const ready = { isPending: false, isError: false, fetchStatus: 'idle', data: [] }

  it('reports a genuinely in-flight query as loading', () => {
    expect(queryPhase(loading)).toBe(QUERY_PHASE.LOADING)
    expect(isQueryLoading(loading)).toBe(true)
    expect(isQueryFailed(loading)).toBe(false)
  })

  it('reports a paused pending query as stalled, never as loading', () => {
    // This is the permanent-skeleton case: pending but not fetching.
    expect(queryPhase(stalled)).toBe(QUERY_PHASE.STALLED)
    expect(isQueryLoading(stalled)).toBe(false)
    expect(isQueryFailed(stalled)).toBe(true)
  })

  it('reports an errored query as failed', () => {
    expect(queryPhase(errored)).toBe(QUERY_PHASE.ERROR)
    expect(isQueryLoading(errored)).toBe(false)
    expect(isQueryFailed(errored)).toBe(true)
  })

  it('reports a settled query as ready', () => {
    expect(queryPhase(ready)).toBe(QUERY_PHASE.READY)
    expect(isQueryLoading(ready)).toBe(false)
    expect(isQueryFailed(ready)).toBe(false)
  })

  it('prefers the error phase when a query is both errored and paused', () => {
    expect(queryPhase({ isPending: false, isError: true, fetchStatus: 'paused' })).toBe(
      QUERY_PHASE.ERROR,
    )
  })

  it('treats a missing query as loading rather than crashing', () => {
    expect(queryPhase(undefined)).toBe(QUERY_PHASE.LOADING)
  })
})
