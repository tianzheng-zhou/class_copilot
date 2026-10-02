import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { LoaderCircle, X, AlertCircle, Check, ChevronDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from './api'

export type Language = 'zh' | 'en'
export const UIContext = createContext<{
  lang: Language
  t: (zh: string, en: string) => string
  notify: (message: string, error?: boolean) => void
}>({ lang: 'zh', t: (zh) => zh, notify: () => {} })
export const useUI = () => useContext(UIContext)
export function useAction() {
  const [busy, setBusy] = useState(false)
  const { notify, lang } = useUI()
  const client = useQueryClient()
  const run = async <T,>(action: () => Promise<T>, success?: string): Promise<T | undefined> => {
    setBusy(true)
    try {
      const value = await action()
      await client.invalidateQueries()
      if (success) notify(success)
      return value
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      notify(
        lang === 'en' && error instanceof ApiError
          ? `${error.code.replaceAll('_', ' ')}. Please review the current state and try again.`
          : message,
        true,
      )
    } finally {
      setBusy(false)
    }
  }
  return { busy, run }
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-mark">✦</div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  )
}
export function Loading() {
  const { t } = useUI()
  return (
    <div className="loading">
      <LoaderCircle size={20} className="spin" />
      {t('加载中…', 'Loading…')}
    </div>
  )
}
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
export function Badge({ state }: { state: string }) {
  const { t } = useUI()
  const states: Record<string, string> = {
    ready: '就绪',
    preparing: '准备中',
    capturing: '录音中',
    finalizing: '录音收尾',
    idle: '待分析',
    queued: '排队中',
    running: '处理中',
    completed: '已完成',
    succeeded: '已完成',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
    cancelling: '正在取消',
    interrupted: '已中断',
    pending: '等待生成',
    streaming: '生成中',
    deleting: '清理中',
    available: '可播放',
    missing: '文件缺失',
  }
  return <span className={`badge ${state}`}>{t(states[state] || state, state.replaceAll('_', ' '))}</span>
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  const { t } = useUI()
  const container = useRef<HTMLElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const root = container.current
    const controls = () =>
      root?.querySelectorAll<HTMLElement>(
        'button:not([disabled]),input:not([disabled]):not([tabindex="-1"]),select:not([disabled]),textarea:not([disabled]),a[href]',
      )
    const elements = controls()
    ;(root?.querySelector<HTMLElement>('[autofocus]') || elements?.[1] || elements?.[0])?.focus()
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const nodes = controls()
      if (!nodes?.length) return
      const first = nodes[0],
        last = nodes[nodes.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    root?.addEventListener('keydown', trap)
    return () => {
      root?.removeEventListener('keydown', trap)
      previous?.focus()
    }
  }, [])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        ref={container}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose()
        }}
      >
        <header>
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label={t('关闭', 'Close')}>
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  )
}
export type SelectOption = { value: string; label: string }
type MenuPlacement = { left: number; width: number; top?: number; bottom?: number; maxHeight: number }
export function Select({
  value,
  options,
  onChange,
  disabled,
  required,
  className,
  'aria-label': ariaLabel,
}: {
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  disabled?: boolean
  required?: boolean
  className?: string
  'aria-label'?: string
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [placement, setPlacement] = useState<MenuPlacement>()
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLUListElement>(null)
  const typed = useRef({ text: '', at: 0 })
  const id = useId()
  const selected = options.findIndex((o) => o.value === value)
  const place = () => {
    const box = trigger.current?.getBoundingClientRect()
    if (!box) return
    const below = innerHeight - box.bottom - 12,
      above = box.top - 12,
      up = below < 220 && above > below
    setPlacement({
      left: box.left,
      width: box.width,
      top: up ? undefined : box.bottom + 5,
      bottom: up ? innerHeight - box.top + 5 : undefined,
      maxHeight: Math.max(120, Math.min(300, up ? above : below)),
    })
  }
  const show = (index = selected) => {
    if (disabled || !options.length) return
    place()
    setActive(Math.max(0, index))
    setOpen(true)
  }
  const choose = (index: number) => {
    const option = options[index]
    setOpen(false)
    trigger.current?.focus()
    if (option && option.value !== value) onChange(option.value)
  }
  useLayoutEffect(() => {
    const node = menu.current
    if (!open || !node || !placement) return
    const overflow = placement.left + node.offsetWidth - (innerWidth - 8)
    node.style.left = `${Math.max(8, placement.left - Math.max(0, overflow))}px`
  }, [open, placement])
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!trigger.current?.contains(target) && !menu.current?.contains(target)) setOpen(false)
    }
    const reposition = (event: Event) => {
      if (event.target !== menu.current) place()
    }
    document.addEventListener('pointerdown', outside)
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', place)
    }
  }, [open])
  useEffect(() => {
    if (open) menu.current?.children[active]?.scrollIntoView({ block: 'nearest' })
  }, [open, active])
  const typeahead = (key: string) => {
    const now = Date.now()
    typed.current = {
      text: (now - typed.current.at < 700 ? typed.current.text : '') + key.toLowerCase(),
      at: now,
    }
    const start = open ? active : selected
    const order = options.map((_, i) => (start + 1 + i) % options.length)
    const match = order.find((i) => options[i].label.toLowerCase().startsWith(typed.current.text))
    if (match !== undefined) show(match)
  }
  const keyDown = (event: ReactKeyboardEvent) => {
    const last = options.length - 1
    const moves: Record<string, number> = {
      ArrowDown: Math.min(last, active + 1),
      ArrowUp: Math.max(0, active - 1),
      Home: 0,
      End: last,
      PageDown: Math.min(last, active + 8),
      PageUp: Math.max(0, active - 8),
    }
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
        event.preventDefault()
        show()
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey)
        typeahead(event.key)
      return
    }
    if (event.key in moves) {
      event.preventDefault()
      setActive(moves[event.key])
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      choose(active)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
    } else if (event.key === 'Tab') setOpen(false)
    else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) typeahead(event.key)
  }
  return (
    <div className={`select${className ? ` ${className}` : ''}`}>
      <button
        ref={trigger}
        type="button"
        role="combobox"
        className={`select-trigger${open ? ' open' : ''}`}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${id}-menu` : undefined}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        aria-required={required || undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={keyDown}
        onKeyUp={(e) => e.key === ' ' && e.preventDefault()}
      >
        <span className="select-value">{options[selected]?.label ?? ''}</span>
        <ChevronDown size={15} className="select-chevron" aria-hidden />
      </button>
      {required && (
        <input
          className="select-validation"
          tabIndex={-1}
          aria-hidden
          required
          value={value}
          onChange={() => {}}
          onFocus={() => trigger.current?.focus()}
        />
      )}
      {open &&
        placement &&
        createPortal(
          <ul
            ref={menu}
            id={`${id}-menu`}
            role="listbox"
            aria-label={ariaLabel}
            className={`select-menu${placement.top === undefined ? ' up' : ''}`}
            style={{
              left: placement.left,
              top: placement.top,
              bottom: placement.bottom,
              minWidth: placement.width,
              maxHeight: placement.maxHeight,
            }}
          >
            {options.map((option, index) => (
              <li
                key={option.value}
                id={`${id}-${index}`}
                role="option"
                aria-selected={index === selected}
                className={`select-option${index === active ? ' active' : ''}`}
                onMouseDown={(e) => e.preventDefault()}
                onMouseMove={() => index !== active && setActive(index)}
                onClick={() => choose(index)}
              >
                <span>{option.label}</span>
                {index === selected && <Check size={14} aria-hidden />}
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </div>
  )
}
export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={18} />
      {error instanceof Error ? error.message : String(error)}
    </div>
  )
}
export function duration(ms: number) {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}
export function dateLabel(value: string, lang = 'zh') {
  return new Date(value).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
export const activeStates = ['queued', 'running', 'cancelling', 'pending', 'streaming']
