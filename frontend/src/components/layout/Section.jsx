import { cn } from '../../lib/cn.js'

/**
 * Arc's layout primitives.
 *
 * These exist because the redesign replaced the card as Arc's default
 * container. A card says "this is a discrete object you can act on", and
 * when every block is one, nothing is. Most separation in Arc is now
 * carried by a rule or by space, and these are the three shapes that takes:
 *
 *   Section    a labelled region of a page
 *   Index      a list whose items sit on shared rules
 *   DataRow    a label/value pair on a rule
 *
 * They are deliberately thin. ARC_DESIGN_SYSTEM.md warns against component
 * abstraction that makes the UI rigid, and the point here is a consistent
 * rhythm, not a framework — each takes a className and gets out of the way.
 */

/**
 * A labelled region.
 *
 * The heading is a `type-label` eyebrow rather than a large heading,
 * because on a page that already has a display-serif subject, a second
 * large heading competes with it. The eyebrow orients without shouting.
 */
export function Section({
  title,
  description,
  actions,
  level = 2,
  className,
  children,
}) {
  const Heading = `h${level}`
  return (
    <section className={cn('min-w-0', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          {title && (
            <Heading className="type-label text-fg-muted">{title}</Heading>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {description && (
        <p className="measure mt-2 text-[13.5px] leading-relaxed text-fg-muted">
          {description}
        </p>
      )}
      <div className={cn(title || description ? 'mt-3' : null)}>{children}</div>
    </section>
  )
}

/**
 * A list whose items sit on shared rules.
 *
 * The top border closes the list at its head so the first item is not
 * orphaned; each item carries its own bottom rule. This is the shape that
 * replaced Arc's `flex flex-col gap-3` card stacks.
 */
export function Index({ as: Tag = 'div', className, children }) {
  return <Tag className={cn('border-t border-line', className)}>{children}</Tag>
}

/**
 * One label/value pair on a rule.
 *
 * Stacks under `sm`, because a two-column grid at 375px gives the value
 * about twelve characters.
 */
export function DataRow({ label, children, className, align = 'start' }) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-1 border-b border-line py-3.5',
        'sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-6',
        align === 'center' && 'sm:items-center',
        className,
      )}
    >
      <dt className="type-label pt-0.5 text-fg-muted">{label}</dt>
      <dd className="min-w-0 text-[14px] text-fg-subtle">{children}</dd>
    </div>
  )
}

/**
 * A figure.
 *
 * Deliberately not a card. A metric is a number with a name, and wrapping
 * each in a bordered box was the single biggest source of Arc's sameness —
 * thirteen of them in a grid on one page. Tabular figures so a column of
 * these lines up.
 */
export function Stat({ label, value, hint, size = 'lg', className }) {
  return (
    <div className={cn('min-w-0', className)}>
      <p className="type-label text-fg-muted">{label}</p>
      <p
        className={cn(
          'mt-1.5 font-medium tabular-nums text-fg',
          size === 'lg' ? 'text-[1.75rem] leading-none' : 'text-xl leading-none',
        )}
      >
        {value}
      </p>
      {hint && (
        <p className="mt-1.5 text-[12.5px] leading-snug text-fg-muted">{hint}</p>
      )}
    </div>
  )
}
