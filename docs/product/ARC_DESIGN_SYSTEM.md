# Arc Design System

**Status:** Proposed frontend design baseline  
**Purpose:** Lightweight, consistent visual and interaction system for Arc V2.

This is a design baseline, not a new frontend architecture. Reuse the existing frontend technology/components where practical.

## 1. Design Direction

Arc should communicate:
- enterprise reliability
- security
- clarity
- technical competence
- calmness
- trust

The interface should be modern without looking like an AI marketing website.

Avoid:
- excessive gradients
- glassmorphism
- glowing borders
- excessive shadows
- decorative AI/sparkle motifs
- excessive animation
- oversized dashboard cards
- inconsistent rounded containers

## 2. Layout

Use a consistent application shell:

```text
┌──────────────────────────────────────────────────┐
│ Top bar / workspace context                      │
├──────────────┬───────────────────────────────────┤
│ Navigation   │ Main content                      │
│              │                                   │
│              │                                   │
└──────────────┴───────────────────────────────────┘
```

Main content should use predictable max-widths, consistent padding, clear page headers and restrained cards.

Do not wrap every piece of information in a card.

## 3. Typography

Use one primary UI typeface unless the existing application already has a well-supported choice.

Establish hierarchy through size, weight, spacing and contrast.

Levels:
- page title
- section heading
- subsection heading
- body
- supporting text
- metadata/caption

Avoid excessive font sizes.

## 4. Color

Use semantic colors:
- neutral/background
- foreground
- muted text
- border
- primary action
- success
- warning
- danger
- informational

Status must never depend on color alone.

Select one palette and reuse it consistently.

## 5. Spacing

Adopt a small spacing scale. Avoid arbitrary one-off margins.

Spacing should communicate hierarchy:
- small: related content
- medium: component groups
- large: sections
- extra-large: page separation

## 6. Navigation

Navigation should:
- identify current location
- support role-aware visibility
- avoid excessive nesting
- distinguish platform and company workspace
- use consistent icons if icons are used

Do not use icons as decoration.

## 7. Buttons

Use a small hierarchy:

### Primary
Main page action.

### Secondary
Alternative action.

### Tertiary/Ghost
Low-emphasis contextual action.

### Destructive
Irreversible/dangerous action.

Do not put multiple competing primary buttons on one screen.

Show disabled and loading states.

## 8. Forms

Inputs provide:
- label
- helper text when needed
- validation state
- error message
- disabled/loading state

Avoid placeholder text as the only label.

Group related fields logically.

## 9. Tables

Use clear headers, consistent row height, readable density, status indicators and predictable actions.

Avoid excessive columns. Use contextual action menus when needed.

## 10. Cards

Cards should represent a meaningful boundary.

Good:
- summaries
- distinct configuration areas
- related information groups

Bad:
- wrapping every paragraph
- wrapping every table
- grids of meaningless metrics

## 11. Dialogs

Dialogs need clear titles, explicit confirmation for risky actions, accessible focus handling, submission states and input preservation where appropriate.

Do not put complex workflows into tiny dialogs. Use full-page configuration when the task is complex.

## 12. Status

Use consistent language:
- Active
- Inactive
- Pending
- Approved
- Rejected
- Failed
- Running
- Completed
- Disabled

Avoid inconsistent synonyms for the same state.

## 13. Empty States

Every empty state answers:
1. What is this area?
2. Why is it empty?
3. What can the user do next?

Do not use empty states as marketing copy.

## 14. Loading States

Use skeletons for content-heavy pages. Match the eventual content shape and avoid layout jumping.

Never leave a page looking like an infinite skeleton when an API has failed.

## 15. Error States

Errors should be visible, understandable, recoverable where possible, and free of stack traces/internal service/database terminology.

Developer diagnostics belong in logs/observability, not normal customer UI.

## 16. Motion

Use motion sparingly for transitions, progress, state changes and feedback.

Respect reduced-motion preferences.

## 17. Accessibility

Every component must support:
- keyboard interaction
- focus visibility
- semantic labels
- appropriate ARIA where needed
- contrast
- accessible status messaging

## 18. Responsive Design

Design from content outward.

Avoid fixed widths that break on smaller screens. Tables need a deliberate responsive strategy. Navigation should collapse predictably.

## 19. Consistency Rule

Before creating a new component, check whether an existing component already provides the required behavior.

Avoid multiple visually different versions of the same semantic:
- buttons
- dialogs
- status badges
- inputs
- tables
- cards
- page headers

## 20. Production Rule

A visually polished component that lies about backend state is not production-ready.

Production quality means:

**visual consistency + correct interaction + honest state + accessibility + permission awareness + reliable failure behavior.**
