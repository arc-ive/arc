# Arc — Visual Language

Design direction for the Arc frontend redesign. Supersedes the visual layer of
`ARC_DESIGN_SYSTEM.md`; the product model, IA and authorization rules in
`ARC_V2_ADR.md` / `ARC_V2_TRD.md` / `ARC_UX_SPEC.md` remain authoritative.

---

## 1. What was wrong

Measured across the running app, not read from source:

| | |
|---|---|
| Composition | Every page is sidebar → breadcrumb → h1 → description → card stack. Ask Arc, Agents, Company Brain, Profile and Settings are the same object with different text. |
| Ask Arc | The product's differentiator is a bordered form floating in ~60% dead space, with the same h1 weight as Settings. |
| Profile | Renders the permission matrix **as** the UI: 23 raw strings (`agent:execute`, `knowledge:read`…) and `GET /auth/me` in the page description. |
| Agents | A CRUD list that surfaces `agent_decision_unavailable` verbatim. |
| Surface | One dark value, one radius, one border, one elevation, everywhere. Nothing is ever emphasised because everything is a card. |
| Type | One sans, one scale, no voice. Nothing distinguishes a document title from a field label from a metric. |
| Context | Platform Console and a customer workspace look identical. V2-ADR-003 makes them distinct planes; the UI does not. |

The diagnosis is not "needs polish". Composition is doing no work.

---

## 2. The idea

**Arc is the record.**

Not an assistant, not a dashboard. Arc holds what a company knows, who decided
what, and what actually ran — and its central promises are evidentiary:
*answers grounded in your own knowledge, with the documents they came from*
(ADR-008), and *approval is not authorization* (ADR-012).

So the visual language is that of a serious institutional record: editorial
typography, a real grid, ink on paper, provenance made visible rather than
decorated. Density where there is evidence to show; air where there is one
thing to read.

This is the opposite of "AI product". No purple, no glow, no particles, no
sparkles, no robot.

---

## 3. Typography

Three roles, chosen for what Arc actually contains.

| Role | Face | Why |
|---|---|---|
| Display | **Newsreader** | An editorial serif drawn for screens. Carries authority without costume. Used for page subjects, answers, and document titles — the things that are *content*. |
| Interface | **Public Sans** | A neutral grotesque commissioned for public-information systems. Legible at 12px, invisible at 15px. Every control, label and table. |
| Data | **IBM Plex Mono** | Arc is full of identifiers, versions and digests. They get a face that says "this is a value", and tabular figures so columns align. |

Deliberately **not Inter** — it is the default that makes generated UI legible
as generated.

Scale is modular (1.25), anchored at 15px interface / 17px prose:

```
display-lg  44/1.05  Newsreader 400   page subject
display     32/1.12  Newsreader 400   section subject
prose       17/1.65  Newsreader 400   answers, document body  (max 68ch)
ui-lg       15/1.5   Public Sans 400  default interface
ui          13/1.45  Public Sans 400  dense tables, secondary
label       11/1.2   Public Sans 600  uppercase, 0.08em  eyebrow / column head
data        13/1.4   Plex Mono 400    ids, versions, digests, figures
```

Serif for content, sans for chrome. That one rule carries most of the hierarchy
and costs nothing.

---

## 4. Colour and surface

Two planes, because Arc has two planes.

**Workspace — paper.** A cool near-white, not warm cream (warm cream + serif +
terracotta is the current house style of generated design). Ink is near-black
with a blue cast.

```
--paper      #F6F7F9     --ink        #101318
--paper-2    #FFFFFF     --ink-2      #3A414D
--rule       #DFE3E9     --ink-3      #6B7480
```

**Platform Console — machine room.** The same type and grid inverted onto
near-black. A platform administrator knows which plane they are on before
reading a word. This is V2-ADR-003 expressed as surface rather than as a badge.

```
--console    #0B0C0E     --console-ink   #ECEEF2
--console-2  #14161A     --console-rule  #262A31
```

**Accent — Arc Ink `#2340D0`.** One saturated blue, used sparingly: the active
nav mark, the focus ring, a link. It is a *marking*, not a fill. It never
carries meaning that status colours carry.

**Status stays separate from brand**: emerald / amber / red / slate for
success, warning, danger, neutral. Colour is never the only channel — every
status pairs with a word, and usually a shape.

Surfaces earn their treatment. Most things are separated by a **rule** (1px)
or by **space**, not by a card. A card means "this is a discrete object you can
act on" — and if everything is one, nothing is.

---

## 5. Navigation

The five-area IA stays exactly as it is, including every permission gate;
`tenantNavForCapabilities` is reused unchanged. Only the presentation changes.

- **Masthead**, not sidebar. Workspace identity sits left, the five areas run
  as a typographic nav, command search and account sit right. This returns the
  full page width to composition — the thing the current layout has least of.
- **Contextual sub-nav** appears under the masthead only where an area has more
  than one surface, as a rule-separated row of links, not a second sidebar.
- **Platform Console** inherits the dark plane, and says `Platform` in the
  masthead where a workspace name would be.
- Breadcrumbs are **removed**. `Tenants › Acme Technologies › Ask Arc` is a
  routing path, not wayfinding, and the masthead already answers "where am I".
- Command palette (⌘K) stays and becomes more prominent — it is the fastest
  navigation Arc has and it was hidden in a corner.

Mobile: the masthead collapses to identity + a sheet trigger; the area nav
becomes a full-height sheet. Not a squeezed sidebar.

---

## 6. Composition

- A 12-column grid with a **content measure** distinct from a **data measure**:
  prose caps at 68ch, tables and traces use the full field.
- **Asymmetry where it means something.** An answer gets the left two-thirds
  and its sources the right third, because sources are marginalia. A document
  index is a single strong column because it is a list.
- **Page subjects, not page headers.** A page opens with its subject set in
  display serif and, where it helps, a single line of orientation — not a
  title/description pair stamped on every route.
- **Empty states say what to do**, set in prose, not an icon tile and a
  sentence in a box.

## 7. Motion

Purposeful and short. There is already a global `prefers-reduced-motion` rule
with `!important`; everything below sits behind it.

| Moment | Treatment |
|---|---|
| Route change | 120ms opacity + 4px rise on the content column only. The masthead never moves. |
| Answer arriving | The answer sets line by line; sources fade in after. This is the one place Arc should feel alive. |
| Timelines (approvals, agent runs) | Steps reveal in sequence at 60ms stagger — the sequence *is* the information. |
| State change | 150ms colour only. Never size, never bounce. |

No parallax. No scroll-jacking. No ambient animation.

## 8. 3D

**Not used.** Three.js was considered for an intelligence visualisation on the
workspace landing. Rejected: Arc's landing surfaces answer "what is in here and
what needs me", and a decorative network graph would answer neither while
costing a WebGL context. A capability being available is not a reason.

---

## 9. Per-area character

One system, five characters.

| Area | Character |
|---|---|
| **Ask Arc** | The answer *is* the page. Question set as a displayed line, answer in prose serif at full measure, sources as numbered marginalia. No chat bubbles — Arc answers from the record, it does not make small talk. |
| **Company Brain** | An editorial index. Documents are rows with typographic hierarchy and real metadata, not identical cards. Search results show the matching passage, which PR-3 already built. |
| **Skills** | A capability sheet. Definition on the left, execution on the right; inputs, constraints and allowed tools as a spec, not a stack of cards. |
| **Agents** | A run trace. Vertical timeline, steps and decisions, state carried by the line itself. |
| **Approvals** | A decision docket. The PR-5 timeline stays — it is the right model — restyled onto the rule-and-space system, with risk leading. |
| **Usage** | Dense and unapologetic. Small multiples and a data table beat thirteen equal tiles; the PR-6 grouping stays. |
| **Platform Console** | The dark plane. Operational, tabular, denser than the workspace. |
| **Profile** | A person's account, not a permission dump. Identity, workspace, role, session, sign-out. Capabilities inform what the app shows — they stop being the content. |

---

## 10. Deliberately removed

- Breadcrumb trail
- The uniform `PageHeader` title+description stamp on every route
- Icon tiles that restate the label beside them
- Card grids as the default container
- The permission matrix as Profile's primary content
- Raw backend strings in the UI (`agent_decision_unavailable` and similar)
- One-radius, one-border, one-elevation surfacing
- Dark-only treatment

## 11. What the references contributed

The attached references are a quality bar, not a source of assets. What was
taken: confidence in large type, the discipline of near-monochrome with a
single restrained accent, rule-and-space separation instead of boxes, generous
measure, and the willingness to let one element dominate a composition.

What was deliberately **not** taken: their palettes, their orange-on-black
signature, their card treatments, their layouts, their branding. Arc's blue on
paper, its serif/grotesque/mono split, and its two-plane surface model are
Arc's own and follow from what Arc contains.
