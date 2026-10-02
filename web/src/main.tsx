import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, Link, NavLink, Outlet, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Settings as SettingsIcon, Sun, Moon, Monitor, Square, X } from 'lucide-react'
import { api, setCsrf, type Bootstrap } from './api'
import { UIContext, type Language, usePageTitle, useUI } from './ui'
import { Library } from './pages/Library'
import { Workspace } from './pages/Workspace'
import { SettingsPage } from './pages/Settings'
import './styles.css'

const client = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1500, retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
})
export type LiveEvent = {
  type: string
  source_id?: string
  job_id?: string
  lesson_id?: string
  content?: string
  db?: number
  peak?: number
  clipping?: boolean
  revision: number
}
export const LiveContext = React.createContext<Record<string, LiveEvent>>({})

function App() {
  const [lang, setLang] = useState<Language>(
    (localStorage.getItem('cc.next.lang') as Language) || (navigator.language.startsWith('zh') ? 'zh' : 'en'),
  )
  const [theme, setTheme] = useState(localStorage.getItem('cc.next.theme') || 'system')
  const [toasts, setToasts] = useState<{ id: number; text: string; error: boolean }[]>([])
  const [live, setLive] = useState<Record<string, LiveEvent>>({})
  const [pageTitle, setPageTitle] = useState<string>()
  const [connected, setConnected] = useState(true)
  const query = useQueryClient()
  const bootstrap = useQuery({
    queryKey: ['bootstrap'],
    queryFn: () => api<Bootstrap>('/bootstrap'),
    refetchInterval: 5000,
  })
  const cursor = useRef<string | null>(null)
  const t = (zh: string, en: string) => (lang === 'zh' ? zh : en)
  useEffect(() => {
    localStorage.setItem('cc.next.theme', theme)
    const media = matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])
  useEffect(() => {
    localStorage.setItem('cc.next.lang', lang)
    document.documentElement.lang = lang
  }, [lang])
  useEffect(() => {
    if (bootstrap.data) setCsrf(bootstrap.data.csrf_token)
  }, [bootstrap.data])
  const initial = bootstrap.data?.event_cursor
  useEffect(() => {
    if (!initial) return
    let disposed = false,
      source: EventSource,
      timer: ReturnType<typeof setTimeout> | undefined
    const connect = (after: string) => {
      source = new EventSource(`/api/v1/events?after=${encodeURIComponent(after)}`)
      source.onopen = () => setConnected(true)
      source.onerror = () => setConnected(false)
      const update = (event: MessageEvent) => {
        const payload = JSON.parse(event.data)
        const previous = cursor.current?.split(':')
        const next = payload.cursor.split(':')
        if (previous && previous[0] === next[0] && +previous[1] >= +next[1]) return
        cursor.current = payload.cursor
        if (!timer)
          timer = setTimeout(() => {
            void query.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'devices' })
            timer = undefined
          }, 160)
      }
      source.addEventListener('entity.updated', update)
      source.addEventListener('entity.deleted', update)
      source.addEventListener('live', (event: MessageEvent) => {
        const item: LiveEvent = JSON.parse(event.data)
        setLive((old) =>
          Object.fromEntries(
            Object.entries({ ...old, [item.source_id || item.job_id || item.type]: item }).slice(-100),
          ),
        )
      })
      source.addEventListener('reset_required', async () => {
        source.close()
        cursor.current = null
        setLive({})
        await query.invalidateQueries()
        try {
          const state = await api<Bootstrap>('/bootstrap')
          setCsrf(state.csrf_token)
          if (!disposed) connect(state.event_cursor)
        } catch {
          setConnected(false)
        }
      })
    }
    connect(cursor.current || initial)
    return () => {
      disposed = true
      source?.close()
      if (timer) clearTimeout(timer)
    }
    // The bootstrap poll must not create a new SSE connection each time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(initial), query])
  const notify = (text: string, error = false) => {
    const id = Date.now() + Math.random()
    setToasts((old) => [...old.slice(-3), { id, text, error }])
    setTimeout(() => setToasts((old) => old.filter((x) => x.id !== id)), 8000)
  }
  const audio = bootstrap.data?.active_audio
  useEffect(() => {
    document.title =
      (audio ? '● ' : '') +
      (pageTitle
        ? `${pageTitle} · Class Copilot`
        : `Class Copilot · ${t('课堂工作台', 'Classroom workspace')}`)
    // t changes identity every render; lang covers it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(audio), pageTitle, lang])
  return (
    <UIContext.Provider value={{ lang, t, notify, setTitle: setPageTitle }}>
      <LiveContext.Provider value={live}>
        <div className="app-shell">
          <aside className="sidebar">
            <Link to="/" className="brand">
              <div className="brand-symbol">
                <BookOpen size={22} />
              </div>
              <span>
                Class Copilot<small>{t('让每一堂课，留下思考', 'A little clarity, every class')}</small>
              </span>
            </Link>
            <div className="nav-label">WORKSPACE</div>
            <nav>
              <NavLink to="/" end>
                <BookOpen size={19} />
                {t('我的课堂', 'My classes')}
              </NavLink>
              <NavLink to="/settings">
                <SettingsIcon size={19} />
                {t('设置与课程', 'Settings & courses')}
              </NavLink>
            </nav>
            <div className="sidebar-note">
              <span className="small-dot" />
              {t('保存在本机', 'Stored on this computer')}
              <p>{t('记录、理解，再多想一步。', 'Capture the lesson. Keep the thinking.')}</p>
            </div>
            <div className="preferences">
              <button onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}>中文 / EN</button>
              <div className="theme-switch">
                {[
                  ['light', Sun],
                  ['dark', Moon],
                  ['system', Monitor],
                ].map(([value, Icon]) => {
                  const I = Icon as typeof Sun
                  return (
                    <button
                      key={String(value)}
                      aria-label={t(
                        value === 'light' ? '浅色' : value === 'dark' ? '深色' : '跟随系统',
                        String(value),
                      )}
                      className={theme === value ? 'selected' : ''}
                      onClick={() => setTheme(String(value))}
                    >
                      <I size={15} />
                    </button>
                  )
                })}
              </div>
            </div>
          </aside>
          <main className="main-area">
            {(!connected || bootstrap.isError) && (
              <div className="connection-banner" role="status">
                {t(
                  '服务连接已断开。后端录音可能仍在继续；恢复连接后会同步记录。',
                  'Disconnected. Backend recording may continue; saved content will sync on reconnect.',
                )}
              </div>
            )}
            {audio && (
              <div className="recording-banner">
                <span className="recording-dot" />
                <Link to={audio.lesson_id ? `/lessons/${audio.lesson_id}` : '/settings'}>
                  {t('后台音频任务', 'Background audio')} · {audio.progress.phase}
                </Link>
                {audio.source_id && (
                  <button
                    onClick={() =>
                      void api(`/sources/${audio.source_id}/stop`, 'POST', {}).catch((e) =>
                        notify(e.message, true),
                      )
                    }
                  >
                    <Square size={12} />
                    {t('停止采集', 'Stop capture')}
                  </button>
                )}
              </div>
            )}
            <Outlet />
          </main>
        </div>
        <div className="toasts" aria-live="polite">
          {toasts.map((toast) => (
            <div className={`toast ${toast.error ? 'error' : ''}`} key={toast.id}>
              {toast.text}
              <button
                onClick={() => setToasts((old) => old.filter((x) => x.id !== toast.id))}
                aria-label={t('关闭', 'Close')}
              >
                <X size={16} />
              </button>
            </div>
          ))}
        </div>
      </LiveContext.Provider>
    </UIContext.Provider>
  )
}
function NotFound() {
  const { t } = useUI()
  usePageTitle(t('页面不存在', 'Page not found'))
  return (
    <div className="page">
      <h1>404</h1>
      <Link to="/">{t('返回课堂列表', 'Back to classes')}</Link>
    </div>
  )
}
const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { path: '/', element: <Library /> },
      { path: '/lessons/:id', element: <Workspace /> },
      { path: '/settings', element: <SettingsPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
)
