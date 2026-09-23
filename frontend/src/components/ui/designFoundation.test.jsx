import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { PageHeader } from './PageHeader.jsx'
import { Badge } from './Badge.jsx'
import { InlineError } from './InlineError.jsx'

const SRC = dirname(dirname(dirname(fileURLToPath(import.meta.url))))

function sourceFiles(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) sourceFiles(full, acc)
    else if (/\.jsx?$/.test(entry) && !/\.test\.jsx?$/.test(entry)) acc.push(full)
  }
  return acc
}

describe('PageHeader', () => {
  it('renders the title as the page h1', () => {
    render(<PageHeader title="Usage" />)
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(h1).toHaveTextContent('Usage')
  })

  it('renders exactly one h1', () => {
    render(<PageHeader title="Usage" description="Something" />)
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('renders a semantic <header>, not an anonymous div', () => {
    // Asserted by element, not by the "banner" role. In the app this sits
    // inside <main>, where a <header> is scoped content and deliberately
    // NOT a banner landmark — the AppShell top bar is the page's only
    // banner. Verified in the browser: 1 banner, 1 header inside main.
    const { container } = render(<PageHeader title="Usage" />)
    expect(container.querySelector('header')).toBeInTheDocument()
  })

  it('omits the description element entirely when there is none', () => {
    const { container } = render(<PageHeader title="Usage" />)
    expect(container.querySelector('p')).toBeNull()
  })

  it('renders actions and meta when supplied', () => {
    render(
      <PageHeader
        title="Skills"
        actions={<button type="button">New skill</button>}
        meta={<Badge variant="success">Active</Badge>}
      />,
    )
    expect(screen.getByRole('button', { name: 'New skill' })).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })
})

describe('Badge', () => {
  it('renders its label as text, never colour alone', () => {
    // ARC_DESIGN_SYSTEM.md §12: status must not depend on colour alone.
    render(<Badge variant="danger">Failed</Badge>)
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('hides the decorative dot from assistive technology', () => {
    const { container } = render(<Badge variant="success" dot>Active</Badge>)
    expect(container.querySelector('[aria-hidden]')).toBeInTheDocument()
  })

  it('falls back to neutral for an unknown variant instead of rendering unstyled', () => {
    // Regression: `variant="zinc"` shipped in ApprovalsPage and produced a
    // badge with no styling at all, because the old colour-named API gave
    // no reason to think the name was wrong.
    //
    // Asserted against an actual neutral badge rather than a hardcoded
    // class string: the behaviour under test is "an unknown variant
    // renders as neutral", and pinning neutral's current utility broke
    // this test the moment that utility was renamed to a token.
    const unknown = render(<Badge variant="chartreuse">Unknown</Badge>)
    const neutral = render(<Badge variant="neutral">Neutral</Badge>)
    expect(unknown.container.firstElementChild.className).toBe(
      neutral.container.firstElementChild.className,
    )
    expect(unknown.container.firstElementChild.className).not.toBe('')
  })

  it('accepts every semantic variant', () => {
    for (const v of ['neutral', 'accent', 'info', 'success', 'warning', 'danger']) {
      const { container, unmount } = render(<Badge variant={v}>{v}</Badge>)
      expect(container.firstElementChild.className).not.toBe('')
      unmount()
    }
  })
})

describe('InlineError', () => {
  it('announces itself — a failure after a user action must not be silent', () => {
    render(<InlineError>Could not save changes.</InlineError>)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save changes.')
  })

  it('renders nothing when there is no message', () => {
    const { container } = render(<InlineError>{null}</InlineError>)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('design foundation is actually adopted', () => {
  const files = sourceFiles(SRC)

  it('scans a meaningful number of files', () => {
    expect(files.length).toBeGreaterThan(40)
  })

  it('no page carries text at a contrast ratio that fails AA', () => {
    // zinc-500 measures 3.70–4.12:1 and zinc-600 measures 2.31–2.57:1 on
    // Arc's four surfaces — both fail AA everywhere they can appear. The
    // muted token is zinc-400 (6.97–7.76:1), the floor that passes.
    const offenders = files.filter((f) =>
      /\btext-zinc-(500|600)\b/.test(readFileSync(f, 'utf8')),
    )
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })

  it('no page hand-rolls the inline error skin', () => {
    const offenders = files
      .filter((f) => f.includes('/pages/'))
      .filter((f) => readFileSync(f, 'utf8').includes('border-red-900/50 bg-red-950/20'))
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })

  it('no page hand-rolls a page-title heading', () => {
    // 22 files each had their own; ARC_DESIGN_SYSTEM.md §19 names page
    // headers specifically as something that must not have variants.
    // Match an actual <h1>, not the utility string: stat-card VALUES share
    // the same classes legitimately, and flagging those would be a false
    // positive that pushes someone to make a number smaller than it should be.
    const offenders = files
      .filter((f) => f.includes('/pages/'))
      .filter((f) =>
        /<h1[^>]*className="[^"]*text-2xl font-semibold tracking-tight/.test(
          readFileSync(f, 'utf8'),
        ),
      )
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })

  it('no component uses a colour-named Badge variant', () => {
    // Badge.jsx itself names the retired variants in its docstring, which is
    // the point — it records why they were removed.
    //
    // This originally matched only the literal attribute form, and 14
    // sites across 11 files were written as expressions —
    // `variant={status === 'active' ? 'green' : 'neutral'}`. Badge falls
    // back to neutral for an unknown variant, so every one of those
    // rendered grey: "active", "healthy" and "received" lost their green,
    // and the error badges lost their red, with nothing failing. The
    // pattern now covers both spellings.
    const RETIRED = /(?:variant="(?:green|amber|red|cyan|indigo|zinc)")|(?:variant=\{[^}]*'(?:green|amber|red|cyan|indigo|zinc)')/
    const offenders = files
      .filter((f) => !f.endsWith('components/ui/Badge.jsx'))
      .filter((f) => RETIRED.test(readFileSync(f, 'utf8')))
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })

  it('no component removes the focus outline', () => {
    // `focus:outline-none` was on 9 controls across 5 pages, each replacing
    // the outline with a 1px border-colour change. A keyboard user gets a
    // hairline shift in hue as their only cue to where they are, which is
    // not a visible focus indicator.
    //
    // Input/Select/Textarea already do this correctly with
    // focus-visible:outline-2 — the forms were simply bypassing them.
    //
    // The one exemption is the skip link's target. `<main tabIndex={-1}>`
    // is a programmatic focus destination, not a keyboard-operable
    // control — WCAG 2.4.7 governs the latter — and a 2px ring drawn
    // around the whole content area reads as a rendering fault. The
    // exemption is keyed to that element, so it cannot quietly widen.
    const offenders = files.filter((f) =>
      readFileSync(f, 'utf8')
        .replace(/<main[^>]*id="main-content"[\s\S]*?>/g, '')
        .includes('focus:outline-none'),
    )
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })

  it('no page hand-rolls a form control class', () => {
    // Three copies of the same `inputClass` string lived in SkillsPage
    // alone. A hand-rolled control skips the label association and the
    // focus ring that the primitives provide.
    const offenders = files
      .filter((f) => f.includes('/pages/'))
      .filter((f) => /const inputClass\s*=/.test(readFileSync(f, 'utf8')))
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })

  it('no component reaches past the semantic layer to a raw colour', () => {
    // ARC_DESIGN_SYSTEM.md's three-layer model — primitive, semantic,
    // component — only holds if components use the semantic layer. About
    // 340 utilities were addressing the primitive scale directly, so a
    // token change would have missed most of the app.
    //
    // index.css is where primitives are allowed to be named, and it is
    // not scanned here.
    const RAW = /(?:^|["'\s:])(?:hover:|focus:|active:|group-hover:|focus-visible:)?(?:text|bg|border|border-[trbl]|ring|divide|from|via|to)-zinc-\d/
    const offenders = files.filter((f) => RAW.test(readFileSync(f, 'utf8')))
    expect(offenders.map((f) => f.replace(SRC, 'src'))).toEqual([])
  })
})
