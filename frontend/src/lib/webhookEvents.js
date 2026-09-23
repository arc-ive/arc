/**
 * The delivery lifecycle of an inbound webhook event.
 *
 * The page had been reading `received` as success — a green tick — and
 * everything else as a warning. That is backwards. `received` means Arc
 * has the event and has not processed it yet; `processed` is the success;
 * `failed` is the only state anyone needs to act on. An operator scanning
 * for problems was being shown ticks against the events still in flight
 * and warnings against the ones that had worked.
 *
 * The record carries `retry_count`, `max_retries` and `next_retry_at`, so
 * a failed event can say whether Arc will try again or has given up —
 * which is the difference between "ignore this" and "someone look at it".
 */

const STAGES = {
  received: {
    label: 'In flight',
    tone: 'neutral',
    detail: 'Arc has the event and has not processed it yet.',
  },
  processed: {
    label: 'Delivered',
    tone: 'success',
    detail: null,
  },
  failed: {
    label: 'Failed',
    tone: 'danger',
    detail: null,
  },
  duplicate: {
    label: 'Duplicate',
    tone: 'neutral',
    detail: 'The sender had already delivered this event; Arc ignored it.',
  },
}

export function deliveryStage(event) {
  const stage = STAGES[event?.status]
  if (stage) return { key: event.status, ...stage }
  return {
    key: event?.status ?? 'unknown',
    label: humanise(event?.status) ?? 'Unknown',
    tone: 'neutral',
    detail: null,
  }
}

/**
 * What happens next to a failed event.
 *
 * Retries exhausted is a different problem from a retry pending: the first
 * needs a person, the second needs patience. Returns null when there is
 * nothing to say, so a delivered event renders no retry line at all.
 */
export function retryState(event) {
  if (!event || event.status !== 'failed') return null
  const count = event.retry_count ?? 0
  const max = event.max_retries ?? 0

  if (count >= max && max > 0) {
    return {
      exhausted: true,
      text: `Gave up after ${count} ${count === 1 ? 'attempt' : 'attempts'}.`,
    }
  }
  const remaining = Math.max(max - count, 0)
  return {
    exhausted: false,
    text:
      `Attempt ${count + 1} of ${max}` +
      (event.next_retry_at ? ` · retries ${relativeFuture(event.next_retry_at)}` : ''),
    remaining,
  }
}

/** A size a person can read, rather than a byte count. */
export function payloadSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n < 0) return null
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/** "in 8 minutes" — the only tense that matters for a pending retry. */
function relativeFuture(iso) {
  const ms = new Date(iso).getTime() - Date.now()
  if (!Number.isFinite(ms)) return 'soon'
  if (ms <= 0) return 'now'
  const minutes = Math.round(ms / 60000)
  if (minutes < 1) return 'in under a minute'
  if (minutes < 60) return `in ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`
  const hours = Math.round(minutes / 60)
  return `in about ${hours} ${hours === 1 ? 'hour' : 'hours'}`
}

function humanise(value) {
  const words = String(value ?? '').replace(/[_-]+/g, ' ').trim()
  if (!words) return null
  return words.charAt(0).toUpperCase() + words.slice(1)
}
