import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { SkipLink } from './SkipLink.jsx'
import { PageHeader } from '../ui/PageHeader.jsx'

const SRC = dirname(dirname(dirname(fileURLToPath(import.meta.url))))

function sourceFiles(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) sourceFiles(full, acc)
    else if (/\.jsx?$/.test(entry) && !/\.test\.jsx?$/.test(entry)) acc.push(full)
  }
  return acc
}

const files = sourceFiles(SRC)

// A source-scanning guard over an empty list passes without checking
// anything. This file was briefly scanning the wrong directory, and every
// guard below reported green while inspecting nothing.
describe('the source scan itself', () => {
  it('actually found the source files', () => {
    expect(files.length).toBeGreaterThan(50)
    expect(files.filter((f) => f.includes('/pages/')).length).toBeGreaterThan(10)
  })
})

describe('SkipLink', () => {
  it('points at the main landmark', () => {
    // Measured before this existed: 20 tab stops between the top of the
    // document and the first control inside <main>, on every page.
    render(<SkipLink />)
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute(
      'href',
      '#main-content',
    )
  })

  it('moves focus into main when activated', async () => {
    // The href alone is not enough, and asserting only the href would have
    // passed on a version that skipped nothing. Verified in the browser:
    // a bare `href="#main-content"` never applied the fragment here
    // (location.hash stayed empty) and the next Tab returned to the first
    // sidebar link. Focus is moved explicitly, so this test drives the
    // click rather than inspecting the markup.
    const user = userEvent.setup()
    render(
      <>
        <SkipLink />
        <main id="main-content" tabIndex={-1}>
          <button type="button">First control</button>
        </main>
      </>,
    )
    await user.click(screen.getByRole('link', { name: 'Skip to content' }))
    expect(document.getElementById('main-content')).toHaveFocus()
  })

  it('stays in the focus order while hidden', () => {
    // `display: none` and `visibility: hidden` both remove an element from
    // the focus order, which would make the link unreachable — the exact
    // failure mode that makes most skip links useless. `sr-only` clips it
    // instead, and it must not carry `hidden`.
    render(<SkipLink />)
    const link = screen.getByRole('link', { name: 'Skip to content' })
    expect(link.className).toContain('sr-only')
    expect(link.className).toContain('focus:not-sr-only')
    expect(link).not.toHaveAttribute('hidden')
  })
})

describe('document title', () => {
  it('is set from the page header', async () => {
    render(<PageHeader title="Approvals" />)
    expect(document.title).toBe('Approvals · Arc')
  })
})

describe('heading structure', () => {
  it('no page jumps from h1 straight to h3', () => {
    // WCAG 1.3.1: heading level conveys structure, and a skipped level
    // tells a screen-reader user there is a section they cannot find.
    // Five files did this, two of them written in this same series of
    // changes — the card titles in a list sit directly under the page h1,
    // so they are h2.
    const offenders = files
      .filter((f) => f.includes('/pages/'))
      .filter((f) => {
        const src = readFileSync(f, 'utf8')
        return src.includes('<h3') && !src.includes('<h2')
      })
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })
})

describe('icon-only controls', () => {
  it('no page labels an icon button with title alone', () => {
    // `title` does compute as an accessible name, but it is the weakest
    // source: it is not announced consistently, never surfaces for
    // keyboard or touch users, and is ignored by some assistive
    // technology. IconButton sets `aria-label` AND `title`; three
    // controls were bypassing it.
    const offenders = files
      .filter((f) => f.includes('/pages/'))
      .filter((f) => /<Button[^>]*\n(?:[^>]*\n)*?\s*title="/.test(readFileSync(f, 'utf8')))
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })
})
