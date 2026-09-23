import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = dirname(dirname(dirname(fileURLToPath(import.meta.url))))
const css = readFileSync(join(SRC, 'index.css'), 'utf8')

/**
 * Contrast is a property of the token pair, so it is checked against the
 * token definitions rather than against a rendered page — every
 * combination at once, including the ones no screen happens to show today.
 *
 * The values here are the audit's own measurements: zinc-400 as the muted
 * floor at 6.97:1 worst case, and zinc-500/600 (3.70:1 and 2.31:1) as the
 * reason the palette stops where it does.
 */

/** Resolve a --color-* token through the primitive layer to a hex value. */
function resolve(name, seen = new Set()) {
  if (seen.has(name)) throw new Error(`circular token: ${name}`)
  seen.add(name)
  const match = css.match(new RegExp(`^\\s*${name}:\\s*([^;]+);`, 'm'))
  if (!match) return null
  const value = match[1].trim()
  const ref = value.match(/^var\((--[a-z0-9-]+)\)$/i)
  return ref ? resolve(ref[1], seen) : value
}

function rgb(hex) {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
}

function luminance([r, g, b]) {
  const f = (v) => {
    const s = v / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function contrast(a, b) {
  const [x, y] = [luminance(rgb(a)), luminance(rgb(b))]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

const SURFACES = [
  '--color-canvas',
  '--color-surface',
  '--color-surface-raised',
  '--color-surface-overlay',
  '--color-surface-selected',
]
const FOREGROUNDS = [
  '--color-fg',
  '--color-fg-subtle',
  '--color-fg-muted',
  '--color-danger',
  '--color-success',
  '--color-warning',
  '--color-info',
  '--color-primary',
]

describe('token contrast', () => {
  it('every foreground clears AA on every surface', () => {
    // 40 pairs. The tightest is primary on surface-selected at 4.99:1 —
    // which is why surface-selected cannot be lightened without moving
    // primary too.
    const failures = []
    for (const fg of FOREGROUNDS) {
      for (const bg of SURFACES) {
        const ratio = contrast(resolve(fg), resolve(bg))
        if (ratio < 4.5) failures.push(`${fg} on ${bg} = ${ratio.toFixed(2)}:1`)
      }
    }
    expect(failures).toEqual([])
  })

  it('the primary button reads as an inversion, not a tint', () => {
    expect(contrast(resolve('--color-on-action'), resolve('--color-action'))).toBeGreaterThan(15)
  })

  it('declares no token that nothing can use', () => {
    // Tailwind v4 tree-shakes an unused @theme entry, so a token no
    // utility references is not merely unused — it is never emitted.
    // getComputedStyle for --color-fg-strong returned "" while the
    // declaration sat in index.css looking authoritative. Three tokens
    // were in that state.
    const declared = [...css.matchAll(/^\s*(--color-[a-z0-9-]+):/gm)].map((m) => m[1])
    const unresolvable = declared.filter((name) => {
      const value = resolve(name)
      return !value || !/^#[0-9a-f]{3,8}$/i.test(value)
    })
    expect(unresolvable).toEqual([])
  })
})
