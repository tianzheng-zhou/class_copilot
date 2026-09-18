import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { LoaderCircle, X, AlertCircle } from 'lucide-react'
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
        'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]',
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
