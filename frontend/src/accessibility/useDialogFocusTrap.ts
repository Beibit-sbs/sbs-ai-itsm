import {
  useEffect,
  useRef,
  type RefObject,
} from 'react'

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',')

function visibleFocusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(focusableSelector),
  ).filter((element) => {
    const style = window.getComputedStyle(element)
    return (
      style.display !== 'none'
      && style.visibility !== 'hidden'
      && !element.hasAttribute('inert')
    )
  })
}

export function useDialogFocusTrap<T extends HTMLElement>(
  active: boolean,
  onClose: () => void,
  initialFocusRef?: RefObject<HTMLElement | null>,
) {
  const dialogRef = useRef<T>(null)
  const closeRef = useRef(onClose)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  closeRef.current = onClose

  useEffect(() => {
    if (!active) return
    const dialog = dialogRef.current
    if (!dialog) return
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    const bodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const initial =
      initialFocusRef?.current
      ?? dialog.querySelector<HTMLElement>('[data-dialog-autofocus]')
      ?? visibleFocusableElements(dialog)[0]
      ?? dialog
    window.setTimeout(() => initial.focus(), 0)

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = visibleFocusableElements(dialog)
      if (focusable.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      } else if (!dialog.contains(document.activeElement)) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = bodyOverflow
      const previous = previousFocusRef.current
      if (previous && document.contains(previous)) {
        window.setTimeout(() => previous.focus(), 0)
      }
    }
  }, [active, initialFocusRef])

  return dialogRef
}
