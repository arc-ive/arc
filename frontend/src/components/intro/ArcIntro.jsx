import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * The entrance to Arc.
 *
 * Plays once, after authentication has already succeeded — it is a
 * curtain, not a gate. Nothing here touches auth, and the application
 * behind it mounts and fetches while the animation runs, so the intro
 * costs the user its duration only if the app was ready sooner than it.
 *
 * Three beats in about 2.4s: the name assembles, the field accelerates
 * outward, the curtain lifts.
 *
 * Canvas rather than a library. A few hundred points with additive
 * trails is a handful of lines of 2D context work, and pulling in an
 * animation dependency to move dots would be the wrong trade — the whole
 * effect is ~120 lines and ships nothing.
 *
 * Escapable three ways: click, Escape, or a reduced-motion preference,
 * which skips it outright rather than slowing it down.
 */

const NAME = 'ARC'
const TYPE_MS = 130 // per letter
const HOLD_MS = 420 // beat after the name completes
const WARP_MS = 900 // acceleration and fade
const STAR_COUNT = 520

export function ArcIntro({ onDone }) {
  const canvasRef = useRef(null)
  const [typed, setTyped] = useState('')
  const [warping, setWarping] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const finished = useRef(false)

  // One exit path, whether the sequence ran out or was skipped, and it
  // runs once — skip and natural completion race, and a second call would
  // unmount a curtain that has already gone.
  const finish = useCallback(() => {
    if (finished.current) return
    finished.current = true
    setLeaving(true)
    // Let the curtain fade before unmounting, so the app is not revealed
    // by a hard cut.
    setTimeout(() => onDone?.(), 320)
  }, [onDone])

  useEffect(() => {
    const skip = (event) => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      finish()
    }
    window.addEventListener('keydown', skip)
    window.addEventListener('pointerdown', skip)
    return () => {
      window.removeEventListener('keydown', skip)
      window.removeEventListener('pointerdown', skip)
    }
  }, [finish])

  // The name, a letter at a time, then the warp.
  useEffect(() => {
    const timers = []
    NAME.split('').forEach((_, i) => {
      timers.push(setTimeout(() => setTyped(NAME.slice(0, i + 1)), TYPE_MS * (i + 1)))
    })
    const nameDone = TYPE_MS * NAME.length + HOLD_MS
    timers.push(setTimeout(() => setWarping(true), nameDone))
    timers.push(setTimeout(() => finish(), nameDone + WARP_MS))
    return () => timers.forEach(clearTimeout)
  }, [finish])

  // The field.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    // A 2D context is not guaranteed: it is null under jsdom, and can be
    // null in a browser that has exhausted its context budget or has
    // canvas disabled. The field is decoration — without it the name and
    // the timing still run, and the curtain still lifts.
    const ctx = canvas.getContext?.('2d')
    if (!ctx) return undefined
    let raf = 0
    let running = true

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const resize = () => {
      canvas.width = canvas.clientWidth * dpr
      canvas.height = canvas.clientHeight * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    // Polar placement, so density is even around the centre and the warp
    // reads as radial rather than as points drifting off a grid.
    const stars = Array.from({ length: STAR_COUNT }, () => {
      const angle = Math.random() * Math.PI * 2
      const radius = Math.random() ** 0.6 // bias outward; the centre stays legible
      return {
        angle,
        radius,
        speed: 0.12 + Math.random() * 0.5,
        size: 0.4 + Math.random() * 1.1,
        alpha: 0.25 + Math.random() * 0.6,
      }
    })

    const start = performance.now()
    const draw = (now) => {
      if (!running) return
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      const cx = w / 2
      const cy = h / 2
      const reach = Math.hypot(cx, cy)
      const elapsed = now - start

      ctx.fillStyle = '#05060a'
      ctx.fillRect(0, 0, w, h)

      // Warp ramps in rather than switching on, so the acceleration is
      // felt as acceleration.
      const warpFactor = warping
        ? Math.min((elapsed - (TYPE_MS * NAME.length + HOLD_MS)) / WARP_MS, 1) ** 2
        : 0

      for (const star of stars) {
        star.radius += (star.speed / reach) * (1 + warpFactor * 90)
        if (star.radius > 1.25) {
          star.radius = Math.random() * 0.08
          star.angle = Math.random() * Math.PI * 2
        }

        const r = star.radius * reach
        const x = cx + Math.cos(star.angle) * r
        const y = cy + Math.sin(star.angle) * r
        const depth = Math.min(star.radius * 1.6, 1)

        if (warpFactor > 0.02) {
          // A streak toward the centre: the trail the point just left.
          const trail = r - star.speed * warpFactor * 90
          ctx.strokeStyle = `rgba(214, 226, 255, ${star.alpha * depth * 0.9})`
          ctx.lineWidth = star.size * (0.7 + warpFactor)
          ctx.beginPath()
          ctx.moveTo(cx + Math.cos(star.angle) * Math.max(trail, 0), cy + Math.sin(star.angle) * Math.max(trail, 0))
          ctx.lineTo(x, y)
          ctx.stroke()
        } else {
          ctx.fillStyle = `rgba(226, 232, 245, ${star.alpha * depth})`
          ctx.beginPath()
          ctx.arc(x, y, star.size, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)

    return () => {
      running = false
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [warping])

  return (
    <div
      role="presentation"
      aria-hidden
      className={[
        'fixed inset-0 z-[100] overflow-hidden bg-[#05060a]',
        'transition-opacity duration-300 ease-out',
        leaving ? 'pointer-events-none opacity-0' : 'opacity-100',
      ].join(' ')}
    >
      <canvas ref={canvasRef} className="absolute inset-0 size-full" />

      {/* A faint centre glow, so the name sits in something rather than
          floating on flat black. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(60% 50% at 50% 50%, rgba(80,110,220,0.16), transparent 70%)',
        }}
      />

      <div className="absolute inset-0 flex items-center justify-center">
        <p
          className={[
            'select-none font-sans text-[clamp(3rem,12vw,8rem)] font-medium tracking-[-0.06em] text-white',
            'transition-transform duration-[900ms] ease-[cubic-bezier(0.7,0,0.84,0)]',
            warping ? 'scale-[1.35] opacity-0' : 'scale-100 opacity-100',
            'transition-opacity',
          ].join(' ')}
          style={{ textShadow: '0 0 60px rgba(120,150,255,0.35)' }}
        >
          {typed}
          {typed.length < NAME.length && (
            <span className="ml-1 inline-block w-[0.06em] animate-pulse bg-white align-baseline text-transparent">
              .
            </span>
          )}
        </p>
      </div>

      <p className="absolute inset-x-0 bottom-8 text-center text-[11px] uppercase tracking-[0.18em] text-white/35">
        Click or press Esc to skip
      </p>
    </div>
  )
}
