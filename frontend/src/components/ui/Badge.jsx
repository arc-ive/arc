import { cn } from '../../lib/cn.js'

/**
 * Status and label badge.
 *
 * Variants are named for MEANING, not colour. The previous API was
 * `neutral | indigo | cyan | green | amber | red`, which had three
 * consequences worth spelling out:
 *
 *  - Nothing enforced that "failed" was always red or "running" always
 *    amber. Each call site picked a colour independently, which is why
 *    ARC_DESIGN_SYSTEM.md §12's status vocabulary had drifted.
 *  - `green` actually rendered emerald, so the name lied about the value.
 *  - An unrecognised variant produced an UNSTYLED badge. A `variant="zinc"`
 *    had been shipping in ApprovalsPage; nothing caught it because the
 *    colour-named API gave no reason to think that name was invalid.
 *
 * Unknown variants now fall back to `neutral` rather than rendering
 * nothing, and every colour comes from the semantic token layer.
 *
 * §12 also requires that status never depends on colour alone. This
 * component renders its children as text, so a badge always carries a
 * label; `dot` is decorative and is hidden from assistive technology.
 */
const VARIANTS = {
  neutral: 'bg-zinc-800/80 text-zinc-200 border-line-strong/60',
  accent: 'bg-primary/10 text-primary border-primary/30',
  info: 'bg-info/10 text-info border-info/30',
  success: 'bg-success/10 text-success border-success/30',
  warning: 'bg-warning/10 text-warning border-warning/30',
  danger: 'bg-danger/10 text-danger border-danger/30',
}

const DOTS = {
  neutral: 'bg-zinc-400',
  accent: 'bg-primary',
  info: 'bg-info',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
}

const SIZES = {
  sm: 'px-1.5 py-px text-[11px]',
  md: 'px-2 py-0.5 text-xs',
}

export function Badge({
  variant = 'neutral',
  size = 'md',
  dot = false,
  className,
  children,
  ...props
}) {
  const tone = VARIANTS[variant] ? variant : 'neutral'

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium tracking-wide',
        VARIANTS[tone],
        SIZES[size] ?? SIZES.md,
        className,
      )}
      {...props}
    >
      {dot && (
        <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', DOTS[tone])} />
      )}
      {children}
    </span>
  )
}
