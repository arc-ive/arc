import { useEffect } from 'react'

export function useDismissable(ref, onDismiss, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined

    const handlePointerDown = (event) => {
      if (ref.current && !ref.current.contains(event.target)) {
        onDismiss()
      }
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onDismiss()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [ref, onDismiss, enabled])
}