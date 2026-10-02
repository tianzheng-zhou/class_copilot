import { useContext, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Download,
  FileText,
  ListChecks,
  MessageSquare,
  Mic,
  MoreHorizontal,
  Pause,
  Play,
  Send,
  Square,
  Upload,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react'
import {
  api,
  upload,
  type Accepted,
  type Answer,
  type Bootstrap,
  type ChatTurn,
  type Device,
  type Job,
  type Page,
  type Question,
  type Snapshot,
  type Settings,
  type Source,
  type Summary,
  type Transcript,
} from '../api'
import {
  Badge,
  Empty,
  ErrorBox,
  Loading,
  Markdown,
  Modal,
  Select,
  activeStates,
  dateLabel,
  duration,
  useAction,
  usePageTitle,
  useUI,
} from '../ui'
import { LiveContext } from '../main'

function useItems<T>(id: string, name: string) {
  return useInfiniteQuery({
    queryKey: [name, id],
    initialPageParam: '',
    queryFn: ({ pageParam }) =>
      api<Page<T>>(
        `/lessons/${id}/${name}?limit=100${pageParam ? '&cursor=' + encodeURIComponent(pageParam) : ''}`,
      ),
    getNextPageParam: (p) => p.next_cursor || undefined,
  })
}
function More({ has, load }: { has: boolean; load: () => void }) {
  const { t } = useUI()
  return has ? (
    <button className="load-more" onClick={load}>
      {t('加载更早内容', 'Load earlier content')}
    </button>
  ) : null
}
function Coverage({ value }: { value: Answer['context_coverage'] }) {
  const { t } = useUI()
  return (
    <details className="coverage">
      <summary>
        {value.truncated
          ? t('上下文已裁剪 · 查看覆盖', 'Context trimmed · view coverage')
          : t('查看内容覆盖', 'View source coverage')}
      </summary>
      {value.source_ranges.map((r, i) => (
        <p key={i}>
          {t('音源', 'Source')} {r.source_id.slice(0, 8)} · {duration(r.start_ms)}–{duration(r.end_ms)}
        </p>
      ))}
      {!!value.gaps.length && (
        <p className="warning-text">
          {value.gaps.length} {t('处未识别区间', 'untranscribed ranges')}
        </p>
      )}
    </details>
  )
}
function Generated({ value }: { value: Answer | ChatTurn['replies'][number] | Summary }) {
  const { t } = useUI()
  const { run, busy } = useAction()
  const live = useContext(LiveContext)
  const draft =
    live[value.job_id]?.type === 'generation.draft' && activeStates.includes(value.state)
      ? live[value.job_id]?.content
      : undefined
  return (
    <div className="generated">
      <div className="generation-meta">
        <Badge state={value.state} />
        <span>{value.model}</span>
        {activeStates.includes(value.state) && (
          <button
            disabled={busy}
            onClick={() => void run(() => api(`/jobs/${value.job_id}/cancel`, 'POST', {}))}
          >
            {t('停止生成', 'Stop')}
          </button>
        )}
        {['failed', 'cancelled', 'interrupted'].includes(value.state) && (
          <button
            disabled={busy}
            onClick={() => void run(() => api(`/jobs/${value.job_id}/retry`, 'POST', {}))}
          >
            {t('重试（新版本）', 'Retry (new version)')}
          </button>
        )}
      </div>
      <Markdown>{draft || value.content || t('等待生成内容…', 'Waiting for content…')}</Markdown>
      {draft && draft !== value.content && (
        <small className="muted">{t('生成草稿 · 尚未全部保存', 'Draft · latest text not yet saved')}</small>
      )}
      {value.error && <p className="warning-text">{value.error.message}</p>}
      <Coverage value={value.context_coverage} />
    </div>
  )
}
function QuestionCard({ question, onLocate }: { question: Question; onLocate: (ids: string[]) => void }) {
  const { t } = useUI()
  const { run, busy } = useAction()
  const [style, setStyle] = useState('brief'),
    [role, setRole] = useState(''),
    [language, setLanguage] = useState('zh'),
    [version, setVersion] = useState('')
  const versions = question.answer_versions
  const latest = versions.findLast((a) => a.state === 'completed') || versions.at(-1)
  const active = versions.findLast((a) => activeStates.includes(a.state))
  const shown = versions.find((a) => a.id === version) || latest
  return (
    <article className="question-card">
      <div className="question-origin">
        {t(
          question.origin === 'auto' ? '课堂提问' : question.origin === 'direct' ? '选段回答' : '手动发现',
          question.origin.replaceAll('_', ' '),
        )}
        <button onClick={() => onLocate(question.segment_ids)}>{t('查看来源', 'Source')}</button>
      </div>
      <h3>{question.text}</h3>
      {shown ? (
        <>
          <div className="version-picker">
            <Select
              aria-label={t('答案版本', 'Answer version')}
              value={shown.id}
              onChange={setVersion}
              options={versions.map((v) => ({
                value: v.id,
                label: `v${v.version} · ${v.style} · ${v.language} · ${v.state}`,
              }))}
            />
          </div>
          <Generated value={shown} />
        </>
      ) : (
        <p className="muted">{t('这个问题还没有参考答案。', 'This question is waiting for an answer.')}</p>
      )}
      {active && active.id !== shown?.id && <Generated value={active} />}
      <details className="answer-options">
        <summary>{t('生成参考答案', 'Generate reference answer')}</summary>
        <div className="inline-options">
          <Select
            aria-label={t('答案详细程度', 'Answer style')}
            value={style}
            onChange={setStyle}
            options={[
              { value: 'brief', label: t('简要', 'Brief') },
              { value: 'detailed', label: t('详细', 'Detailed') },
            ]}
          />
          <Select
            aria-label={t('答案语言', 'Answer language')}
            value={language}
            onChange={setLanguage}
            options={[
              { value: 'zh', label: '中文' },
              { value: 'en', label: 'English' },
              { value: 'bilingual', label: t('中英双语', 'Bilingual') },
            ]}
          />
          <Select
            aria-label={t('答案模型', 'Answer model')}
            value={role}
            onChange={setRole}
            options={[
              { value: '', label: t('默认模型', 'Default model') },
              { value: 'fast', label: t('快速', 'Fast') },
              { value: 'quality', label: t('质量', 'Quality') },
            ]}
          />
        </div>
        <button
          disabled={busy || !!active}
          onClick={() =>
            void run(() =>
              api(`/questions/${question.id}/answers`, 'POST', {
                style,
                language,
                ...(role ? { model_role: role } : {}),
              }),
            )
          }
        >
          {t('生成新版本', 'Generate new version')}
        </button>
      </details>
      <small className="ai-label">
        {t('AI 参考答案，请结合课堂核实', 'AI reference answer · check against your class')}
      </small>
    </article>
  )
}
function AudioPlayer({
  src,
  fallbackMs,
  register,
}: {
  src: string
  fallbackMs: number
  register: (node: HTMLAudioElement | null) => void
}) {
  const { t } = useUI()
  const audio = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [speed, setSpeed] = useState('1')
  const [current, setCurrent] = useState(0)
  const [total, setTotal] = useState(fallbackMs / 1000)
  const progress = total ? Math.min(100, (current / total) * 100) : 0
  return (
    <div className="player">
      <audio
        ref={(node) => {
          audio.current = node
          register(node)
        }}
        preload="none"
        src={src}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) =>
          Number.isFinite(e.currentTarget.duration) && setTotal(e.currentTarget.duration)
        }
        onRateChange={(e) => setSpeed(String(e.currentTarget.playbackRate))}
        onVolumeChange={(e) => setMuted(e.currentTarget.muted)}
      />
      <button
        className="player-toggle"
        aria-label={playing ? t('暂停', 'Pause') : t('播放', 'Play')}
        onClick={() => {
          const node = audio.current
          if (!node) return
          if (node.paused) void node.play().catch(() => {})
          else node.pause()
        }}
      >
        {playing ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
      </button>
      <span className="player-time mono">{duration(current * 1000)}</span>
      <input
        type="range"
        className="player-seek"
        aria-label={t('播放进度', 'Seek')}
        min={0}
        max={total || 0}
        step={0.1}
        value={Math.min(current, total)}
        disabled={!total}
        style={{ '--progress': `${progress}%` } as CSSProperties}
        onChange={(e) => {
          const time = +e.target.value
          setCurrent(time)
          if (audio.current) audio.current.currentTime = time
        }}
      />
      <span className="player-time mono">{duration(total * 1000)}</span>
      <button
        className="icon-button"
        aria-label={muted ? t('取消静音', 'Unmute') : t('静音', 'Mute')}
        aria-pressed={muted}
        onClick={() => audio.current && (audio.current.muted = !audio.current.muted)}
      >
        {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
      </button>
      <Select
        aria-label={t('播放速度', 'Playback speed')}
        value={speed}
        onChange={(value) => {
          setSpeed(value)
          if (audio.current) audio.current.playbackRate = +value
        }}
        options={['0.75', '1', '1.25', '1.5', '2'].map((n) => ({ value: n, label: `${n}×` }))}
      />
    </div>
  )
}
function SourceCard({
  source,
  playRefs,
  onAnalyze,
}: {
  source: Source
  playRefs: React.MutableRefObject<Record<string, HTMLAudioElement | null>>
  onAnalyze: (source: Source) => void
}) {
  const { t } = useUI()
  const { run, busy } = useAction()
  const [minutes, setMinutes] = useState('')
  const playable = source.assets.find((a) => a.role === 'playback')
  const original = source.assets.find((a) => a.role === 'original')
  const recording = ['capturing', 'preparing', 'finalizing'].includes(source.capture_state)
  return (
    <article className="source-card">
      <div className="source-heading">
        <strong>
          {source.ordinal.toString().padStart(2, '0')} ·{' '}
          {source.original_filename || source.device_label || t('录音', 'Recording')}
        </strong>
        <span>{duration(source.duration_ms)}</span>
      </div>
      <div className="source-badges">
        <Badge state={source.capture_state} />
        <Badge state={source.transcription_state} />
        <span className="muted">
          {t('已识别', 'Transcribed')} {duration(source.transcribed_ms)}
        </span>
      </div>
      {playable ? (
        <AudioPlayer
          src={playable.url}
          fallbackMs={source.duration_ms}
          register={(node) => {
            playRefs.current[source.id] = node
          }}
        />
      ) : (
        <p className="muted">
          {t(
            '分析或录音收尾后可播放 MP3；导入原件始终保留。',
            'MP3 playback becomes available after analysis or recording finalization.',
          )}
        </p>
      )}
      <div className="source-actions">
        {playable && <a href={playable.url + '?download=true'}>{t('下载 MP3', 'Download MP3')}</a>}
        {original && <a href={original.url + '?download=true'}>{t('下载原文件', 'Download original')}</a>}
        {!recording && source.transcription_state !== 'completed' && (
          <button
            disabled={busy || activeStates.includes(source.transcription_state)}
            onClick={() => onAnalyze(source)}
          >
            {source.transcription_state === 'idle'
              ? t('开始分析', 'Analyze')
              : t('补识别', 'Resume analysis')}
          </button>
        )}
        {recording && (
          <button
            disabled={source.capture_state === 'finalizing' || busy}
            onClick={() => void run(() => api(`/sources/${source.id}/stop`, 'POST', {}))}
          >
            {t('停止采集', 'Stop capture')}
          </button>
        )}
      </div>
      {source.capture_state === 'capturing' && (
        <div className="timer-edit">
          <input
            aria-label={t('自动停止分钟数', 'Auto stop minutes')}
            type="number"
            min="1"
            max="240"
            placeholder={t('不限时', 'No timer')}
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
          <button
            onClick={() => {
              const value = minutes ? +minutes : null
              if (
                value &&
                source.started_at &&
                Date.now() - new Date(source.started_at).getTime() >= value * 60000 &&
                !confirm(t('该时长已经过去，将立即停止。继续？', 'That duration has elapsed. Stop now?'))
              )
                return
              void run(() =>
                api(`/sources/${source.id}`, 'PATCH', { auto_stop_minutes: value }, source.revision),
              )
            }}
          >
            {t('应用计时', 'Set timer')}
          </button>
        </div>
      )}
      {source.error && <p className="warning-text">{source.error.message}</p>}
      {source.gap_ranges.map((g, i) => (
        <p className="warning-text" key={i}>
          {t('未识别', 'Untranscribed')} {duration(g.start_ms)}–{duration(g.end_ms)} · {g.reason}
        </p>
      ))}
    </article>
  )
}
export function Workspace() {
  const { id = '' } = useParams()
  const { t, lang, notify } = useUI()
  const { run, busy } = useAction()
  const live = useContext(LiveContext)
  const snapshot = useQuery({
    queryKey: ['snapshot', id],
    queryFn: () => api<Snapshot>(`/lessons/${id}/snapshot`),
  })
  const transcriptQuery = useItems<Transcript>(id, 'transcripts'),
    questionQuery = useItems<Question>(id, 'questions'),
    chatQuery = useItems<ChatTurn>(id, 'chat-turns'),
    sourceQuery = useItems<Source>(id, 'sources'),
    summaryQuery = useItems<Summary>(id, 'summaries')
  const bootstrap = useQuery({ queryKey: ['bootstrap'], queryFn: () => api<Bootstrap>('/bootstrap') })
  const jobs = useQuery({
    queryKey: ['jobs', id],
    queryFn: () => api<Page<Job>>(`/jobs?lesson_id=${id}&limit=100`),
  })
  const [panel, setPanel] = useState('transcripts'),
    [drawer, setDrawer] = useState<'sources' | 'summaries' | 'jobs' | null>(null)
  const [selection, setSelection] = useState<string[]>([]),
    [recordModal, setRecordModal] = useState(false),
    [kind, setKind] = useState('microphone'),
    [device, setDevice] = useState(''),
    [minutes, setMinutes] = useState('')
  const [draft, setDraft] = useState(() => localStorage.getItem('cc.next.draft.' + id) || ''),
    [role, setRole] = useState('fast'),
    [thinking, setThinking] = useState(false)
  const [analysisSource, setAnalysisSource] = useState<Source | null>(null),
    [autoSummary, setAutoSummary] = useState(true),
    [includeChat, setIncludeChat] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null),
    [summaryChat, setSummaryChat] = useState(false)
  const [widths, setWidths] = useState([34, 33, 33]),
    [clock, setClock] = useState(Date.now())
  const uploadCancel = useRef<(() => void) | null>(null),
    fileInput = useRef<HTMLInputElement>(null),
    playRefs = useRef<Record<string, HTMLAudioElement | null>>({}),
    board = useRef<HTMLDivElement>(null)
  const savedSettings = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/settings') })
  const devices = useQuery({
    queryKey: ['devices', kind],
    queryFn: () =>
      api<{ devices: Device[]; unavailable_reason: string | null }>(`/audio/devices?kind=${kind}`),
    enabled: recordModal,
  })
  useEffect(() => {
    setDraft(localStorage.getItem('cc.next.draft.' + id) || '')
    setSelection([])
  }, [id])
  useEffect(() => {
    localStorage.setItem('cc.next.draft.' + id, draft)
  }, [id, draft])
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    if (devices.data && !device && !savedSettings.data?.audio.default_device_id)
      setDevice(devices.data.devices.find((d) => d.is_default)?.id || devices.data.devices[0]?.id || '')
  }, [devices.data, device, savedSettings.data])
  useEffect(() => {
    if (recordModal && savedSettings.data) {
      setKind(savedSettings.data.audio.default_kind)
      setDevice(savedSettings.data.audio.default_device_id || '')
      setMinutes(savedSettings.data.audio.auto_stop_minutes?.toString() || '')
    }
  }, [recordModal])
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawer(null)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])
  const transcripts =
    transcriptQuery.data?.pages.toReversed().flatMap((p) => p.items) || snapshot.data?.transcripts.items || []
  const questions =
    questionQuery.data?.pages.toReversed().flatMap((p) => p.items) || snapshot.data?.questions.items || []
  const chats =
    chatQuery.data?.pages.toReversed().flatMap((p) => p.items) || snapshot.data?.chat_turns.items || []
  const sources =
    sourceQuery.data?.pages.toReversed().flatMap((p) => p.items) || snapshot.data?.sources.items || []
  const summaries =
    summaryQuery.data?.pages.toReversed().flatMap((p) => p.items) || snapshot.data?.summaries.items || []
  const current = sources.find((s) => ['capturing', 'preparing', 'finalizing'].includes(s.capture_state))
  const chatBusy = jobs.data?.items.some((j) => j.kind === 'chat_reply' && activeStates.includes(j.state))
  const lesson = snapshot.data?.lesson
  const lessonTitle =
    lesson && (lesson.custom_title || `${lesson.course_name} · ${dateLabel(lesson.created_at, lang)}`)
  usePageTitle(
    lessonTitle && current?.capture_state === 'capturing'
      ? `${t('录音中', 'Recording')} · ${lessonTitle}`
      : lessonTitle,
  )
  const select = (identity: string) =>
    setSelection((old) =>
      old.includes(identity) ? old.filter((x) => x !== identity) : [...old, identity].slice(-100),
    )
  const jump = (segment: Transcript) => {
    setDrawer('sources')
    setTimeout(() => {
      const player = playRefs.current[segment.source_id]
      if (player) {
        player.currentTime = segment.start_ms / 1000
        void player.play().catch(() => {})
      } else notify(t('该来源还没有可播放的 MP3', 'Playback is not available for this source yet'))
    }, 80)
  }
  const send = () => {
    if (!draft.trim() || chatBusy) return
    void run(async () => {
      await api(`/lessons/${id}/chat-turns`, 'POST', { content: draft.trim(), model_role: role, thinking })
      setDraft('')
    })
  }
  const resize = (index: number, startX: number) => {
    const initial = [...widths]
    const move = (event: PointerEvent) => {
      const delta = ((event.clientX - startX) / (board.current?.clientWidth || 1)) * 100
      const next = [...initial]
      next[index] = Math.max(20, Math.min(initial[index] + initial[index + 1] - 20, initial[index] + delta))
      next[index + 1] = initial[index] + initial[index + 1] - next[index]
      setWidths(next)
    }
    const end = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
  }
  if (snapshot.isLoading) return <Loading />
  if (snapshot.isError) return <ErrorBox error={snapshot.error} />
  if (!lesson) return null
  return (
    <div className="workspace">
      <div className="work-heading">
        <div>
          <Link to="/" className="back-link">
            <ArrowLeft size={15} />
            {lesson.course_name}
          </Link>
          <h1>{lessonTitle}</h1>
        </div>
        <div className="work-actions">
          <a
            className="icon-button"
            href={`/api/v1/lessons/${id}/export`}
            title={t('导出完整 Markdown', 'Export complete Markdown')}
          >
            <Download size={19} />
          </a>
          <button onClick={() => setDrawer('sources')}>
            <Upload size={16} />
            {t('音频来源', 'Audio')}
          </button>
          {current ? (
            <button
              className="stop-button"
              disabled={current.capture_state === 'finalizing'}
              onClick={() => void run(() => api(`/sources/${current.id}/stop`, 'POST', {}))}
            >
              <Square size={15} />
              {t('停止采集', 'Stop capture')}
            </button>
          ) : (
            <button
              className="primary"
              disabled={!bootstrap.data?.configured || !!bootstrap.data?.active_audio}
              onClick={() => setRecordModal(true)}
            >
              <Mic size={16} />
              {t('开始录音', 'Record')}
            </button>
          )}
        </div>
      </div>
      <div className="work-toolbar">
        <label className="mode-select">
          {t('处理方式', 'Processing')}
          <Select
            value={lesson.automation_mode}
            disabled={busy}
            onChange={(mode) =>
              void run(() => api(`/lessons/${id}/automation`, 'PUT', { mode }, lesson.revision))
            }
            options={[
              { value: 'auto_answer', label: t('自动问答', 'Auto answers') },
              { value: 'detect_only', label: t('仅检测问题', 'Detect questions') },
              { value: 'transcribe_only', label: t('仅转写', 'Transcribe only') },
            ]}
          />
        </label>
        <div className="record-status">
          {current ? (
            <>
              <Badge state={current.capture_state} />
              <span className="mono">
                {duration(
                  current.started_at ? Math.max(0, clock - new Date(current.started_at).getTime()) : 0,
                )}
              </span>
              <meter
                min="-100"
                max="0"
                value={live[current.id]?.db || -100}
                aria-label={t('录音音量', 'Capture level')}
              />
              <span className="muted">
                {t('已识别', 'Transcribed')} {duration(current.transcribed_ms)}
              </span>
              {current.stop_at && (
                <span className="mono">
                  {t('剩余', 'Left')} {duration(Math.max(0, new Date(current.stop_at).getTime() - clock))}
                </span>
              )}
            </>
          ) : (
            <span className="muted">
              <span className="small-dot" />
              {t('课后也可以继续提问和总结', 'Keep asking questions after class')}
            </span>
          )}
        </div>
        <button onClick={() => setDrawer('summaries')}>
          <FileText size={16} />
          {t('课堂总结', 'Summary')}
        </button>
        <button className="icon-button" aria-label={t('任务记录', 'Tasks')} onClick={() => setDrawer('jobs')}>
          <MoreHorizontal size={19} />
        </button>
      </div>
      {!bootstrap.data?.configured && (
        <div className="notice">
          <span>{t('尚未配置模型服务。', 'AI service is not configured.')}</span>
          <Link to="/settings">{t('前往设置', 'Open settings')}</Link>
        </div>
      )}
      <div className="mobile-panels">
        {[
          ['transcripts', t('转写', 'Transcript')],
          ['questions', t('问答', 'Q&A')],
          ['chat', t('聊天', 'Chat')],
        ].map(([key, label]) => (
          <button key={key} className={panel === key ? 'selected' : ''} onClick={() => setPanel(key)}>
            {label}
          </button>
        ))}
      </div>
      <div
        className="workspace-board"
        ref={board}
        style={
          {
            '--col1': `${widths[0]}fr`,
            '--col2': `${widths[1]}fr`,
            '--col3': `${widths[2]}fr`,
          } as CSSProperties
        }
      >
        <section className={`work-panel transcript-panel ${panel === 'transcripts' ? 'mobile-active' : ''}`}>
          <header>
            <h2>
              <ListChecks size={18} />
              {t('课堂转写', 'Transcript')}
            </h2>
            <span className="count">{transcriptQuery.data?.pages[0]?.total || 0}</span>
          </header>
          <div className="panel-scroll">
            <More has={transcriptQuery.hasNextPage} load={() => void transcriptQuery.fetchNextPage()} />
            {!transcripts.length ? (
              <Empty title={t('让课堂，变成可回顾的文字', 'Turn class into something you can revisit')}>
                {t(
                  '开始录音，或导入已有音频。持续转写会出现在这里。',
                  'Start recording or import audio. Your transcript will appear here.',
                )}
              </Empty>
            ) : (
              transcripts.map((segment) => (
                <article
                  className={`transcript-row ${selection.includes(segment.id) ? 'checked' : ''}`}
                  key={segment.id}
                  id={'segment-' + segment.id}
                >
                  <div className="transcript-meta">
                    <label>
                      <input
                        type="checkbox"
                        checked={selection.includes(segment.id)}
                        onChange={() => select(segment.id)}
                        aria-label={t('选择片段', 'Select segment') + ' ' + segment.ordinal}
                      />
                      <span>
                        {segment.source_ordinal.toString().padStart(2, '0')} / {duration(segment.start_ms)}
                      </span>
                    </label>
                    <button
                      className="icon-button"
                      aria-label={t('播放此片段', 'Play this segment')}
                      onClick={() => jump(segment)}
                    >
                      <Play size={13} />
                    </button>
                  </div>
                  <p>{segment.text}</p>
                </article>
              ))
            )}
            {current && live[current.id]?.type === 'transcription.draft' && (
              <div className="transcript-draft">
                <Badge state="streaming" />
                <p>{live[current.id]?.content}</p>
                <small>{t('识别草稿，完成后保存', 'Draft; saved when complete')}</small>
              </div>
            )}
          </div>
          <footer className="selection-bar">
            <span>
              {selection.length} {t('个片段已选', 'selected')}
            </span>
            <button
              disabled={!selection.length || busy}
              onClick={() =>
                void run(() => api(`/lessons/${id}/question-detections`, 'POST', { segment_ids: selection }))
              }
            >
              {t('找问题', 'Find questions')}
            </button>
            <button
              disabled={!selection.length || busy}
              onClick={() =>
                void run(() => api(`/lessons/${id}/direct-answers`, 'POST', { segment_ids: selection }))
              }
            >
              {t('回答选段', 'Explain selection')}
            </button>
          </footer>
        </section>
        <div
          role="separator"
          aria-label={t('调整转写栏宽度', 'Resize transcript')}
          aria-orientation="vertical"
          tabIndex={0}
          className="resize-handle"
          onPointerDown={(e) => resize(0, e.clientX)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight')
              setWidths([Math.min(45, widths[0] + 1), Math.max(20, widths[1] - 1), widths[2]])
            if (e.key === 'ArrowLeft')
              setWidths([Math.max(20, widths[0] - 1), Math.min(45, widths[1] + 1), widths[2]])
          }}
        />
        <section className={`work-panel questions-panel ${panel === 'questions' ? 'mobile-active' : ''}`}>
          <header>
            <h2>
              <FileText size={18} />
              {t('课堂问答', 'Class questions')}
            </h2>
            <span className="count">{questionQuery.data?.pages[0]?.total || 0}</span>
          </header>
          <div className="panel-scroll">
            <More has={questionQuery.hasNextPage} load={() => void questionQuery.fetchNextPage()} />
            {!questions.length ? (
              <Empty title={t('好问题，值得多想一步', 'A good question is a place to begin')}>
                {t(
                  '自动检测到的问题会出现在这里。也可以选择转写片段，主动找问题或直接回答。',
                  'Detected questions appear here. You can also select transcript segments to ask for an explanation.',
                )}
              </Empty>
            ) : (
              questions.map((q) => (
                <QuestionCard
                  key={q.id}
                  question={q}
                  onLocate={(ids) => {
                    setSelection(ids)
                    setPanel('transcripts')
                    document
                      .getElementById('segment-' + ids[0])
                      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                  }}
                />
              ))
            )}
          </div>
        </section>
        <div
          role="separator"
          aria-label={t('调整问答栏宽度', 'Resize questions')}
          aria-orientation="vertical"
          tabIndex={0}
          className="resize-handle"
          onPointerDown={(e) => resize(1, e.clientX)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight')
              setWidths([widths[0], Math.min(45, widths[1] + 1), Math.max(20, widths[2] - 1)])
            if (e.key === 'ArrowLeft')
              setWidths([widths[0], Math.max(20, widths[1] - 1), Math.min(45, widths[2] + 1)])
          }}
        />
        <section className={`work-panel chat-panel ${panel === 'chat' ? 'mobile-active' : ''}`}>
          <header>
            <h2>
              <MessageSquare size={18} />
              {t('继续思考', 'Keep thinking')}
            </h2>
            <span className="subtle-label">{t('课堂聊天', 'CLASS CHAT')}</span>
          </header>
          <div className="panel-scroll chat-scroll">
            <More has={chatQuery.hasNextPage} load={() => void chatQuery.fetchNextPage()} />
            {!chats.length ? (
              <Empty title={t('哪里还想再听一遍？', 'What would you like to understand?')}>
                {transcripts.length
                  ? t(
                      '追问一个概念，换一个例子，或梳理你的思路。',
                      'Explore a concept, ask for another example, or work through an idea.',
                    )
                  : t(
                      '当前还没有课堂上下文，也可以先问一个一般问题。',
                      'There is no classroom context yet. You can still ask a general question.',
                    )}
              </Empty>
            ) : (
              chats.map((turn) => (
                <div key={turn.id} className="chat-turn">
                  <div className="user-message">{turn.user_content}</div>
                  {turn.replies.map((reply) => (
                    <div key={reply.id} className="assistant-message">
                      <div className="assistant-label">
                        ✦ COPILOT <span>#{reply.attempt}</span>
                      </div>
                      <Generated value={reply} />
                    </div>
                  ))}
                  <button
                    className="text-button"
                    disabled={busy || chatBusy}
                    onClick={() =>
                      void run(() =>
                        api(`/chat-turns/${turn.id}/replies`, 'POST', { model_role: role, thinking }),
                      )
                    }
                  >
                    {t('重新回答（保留版本）', 'Answer again (keep versions)')}
                  </button>
                </div>
              ))
            )}
          </div>
          <footer className="chat-composer">
            <textarea
              aria-label={t('聊天消息', 'Chat message')}
              placeholder={t('问一个问题，或分享你的想法…', 'Ask a question, or share a thought…')}
              value={draft}
              maxLength={20000}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <div className="composer-options">
              <Select
                value={role}
                onChange={setRole}
                aria-label={t('聊天模型', 'Chat model')}
                options={[
                  { value: 'fast', label: t('快速', 'Fast') },
                  { value: 'quality', label: t('质量', 'Quality') },
                ]}
              />
              <label className="checkbox-label">
                <input type="checkbox" checked={thinking} onChange={(e) => setThinking(e.target.checked)} />
                {t('思考', 'Thinking')}
              </label>
              <button
                className="send-button"
                disabled={busy || chatBusy || !draft.trim() || !bootstrap.data?.configured}
                onClick={send}
                aria-label={t('发送消息', 'Send message')}
              >
                <Send size={17} />
              </button>
            </div>
            <small>
              {chatBusy
                ? t('正在回复，草稿会保留', 'Reply in progress. Your draft is saved.')
                : t('Enter 发送 · Shift + Enter 换行', 'Enter to send · Shift + Enter for a new line')}
            </small>
          </footer>
        </section>
      </div>
      {drawer && (
        <div className="drawer-backdrop" onClick={() => setDrawer(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <header>
              <h2>
                {drawer === 'sources'
                  ? t('音频来源', 'Audio sources')
                  : drawer === 'summaries'
                    ? t('课堂总结', 'Class summaries')
                    : t('任务记录', 'Task history')}
              </h2>
              <button
                className="icon-button"
                aria-label={t('关闭面板', 'Close panel')}
                onClick={() => setDrawer(null)}
              >
                <X size={20} />
              </button>
            </header>
            {drawer === 'sources' ? (
              <>
                <p className="muted">
                  {t(
                    '录音来自后端所在电脑；上传支持 MP3、WAV、M4A、FLAC、OGG，最大 500 MiB / 4 小时。',
                    'Recording uses the server computer. Import MP3, WAV, M4A, FLAC or OGG, up to 500 MiB / 4 hours.',
                  )}
                </p>
                <input
                  ref={fileInput}
                  hidden
                  type="file"
                  accept=".mp3,.wav,.m4a,.flac,.ogg"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (!file) return
                    if (file.size > 500 * 1024 * 1024) {
                      notify(t('文件超过 500 MiB', 'File exceeds 500 MiB'), true)
                      return
                    }
                    setUploadProgress(0)
                    const operation = upload(id, file, setUploadProgress)
                    uploadCancel.current = operation.cancel
                    void run(async () => {
                      try {
                        const source = await operation.promise
                        setAnalysisSource(source)
                      } finally {
                        setUploadProgress(null)
                        uploadCancel.current = null
                        if (fileInput.current) fileInput.current.value = ''
                      }
                    })
                  }}
                />
                {uploadProgress === null ? (
                  <button className="primary full-width" onClick={() => fileInput.current?.click()}>
                    <Upload size={17} />
                    {t('导入录音', 'Import audio')}
                  </button>
                ) : (
                  <div className="upload-progress">
                    <progress max="100" value={uploadProgress} />
                    <span>
                      {uploadProgress}% ·{' '}
                      {uploadProgress === 100
                        ? t('校验音频中', 'Validating audio')
                        : t('上传中', 'Uploading')}
                    </span>
                    <button onClick={() => uploadCancel.current?.()}>{t('取消上传', 'Cancel upload')}</button>
                  </div>
                )}
                <More has={sourceQuery.hasNextPage} load={() => void sourceQuery.fetchNextPage()} />
                {sources.length ? (
                  sources.map((source) => (
                    <SourceCard
                      key={source.id}
                      source={source}
                      playRefs={playRefs}
                      onAnalyze={setAnalysisSource}
                    />
                  ))
                ) : (
                  <Empty title={t('还没有音频', 'No audio yet')}>
                    {t(
                      '可以录制一堂新课，也可以导入已有文件。',
                      'Record a new lesson or import an existing file.',
                    )}
                  </Empty>
                )}
              </>
            ) : drawer === 'summaries' ? (
              <>
                <p className="muted">
                  {t(
                    '从知识点、课堂问题和待确认内容中整理复习材料。每次生成都会保留一个新版本。',
                    'Review key concepts, classroom questions and uncertainties. Each generation creates a new version.',
                  )}
                </p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={summaryChat}
                    onChange={(e) => setSummaryChat(e.target.checked)}
                  />
                  {t('将聊天纳入本次总结', 'Include chat in this summary')}
                </label>
                <button
                  className="primary full-width"
                  disabled={
                    busy ||
                    !transcripts.length ||
                    jobs.data?.items.some(
                      (j) => j.kind === 'summarize_lesson' && activeStates.includes(j.state),
                    )
                  }
                  onClick={() =>
                    void run(() => api(`/lessons/${id}/summaries`, 'POST', { include_chat: summaryChat }))
                  }
                >
                  {t('生成新的总结', 'Generate new summary')}
                </button>
                <More has={summaryQuery.hasNextPage} load={() => void summaryQuery.fetchNextPage()} />
                {summaries.toReversed().map((summary) => (
                  <article className="summary-card" key={summary.id}>
                    <h3>
                      {t('总结', 'Summary')} v{summary.version}
                    </h3>
                    {summary.is_stale && (
                      <p className="warning-text">
                        {t(
                          '有新内容，可重新生成总结',
                          'New content is available. Generate an updated summary.',
                        )}
                      </p>
                    )}
                    <Generated value={summary} />
                  </article>
                ))}
                {!summaries.length && (
                  <Empty title={t('把一堂课，整理成自己的理解', 'Turn a class into your own understanding')}>
                    {t('有最终转写后，即可生成总结。', 'Generate a summary once a transcript is available.')}
                  </Empty>
                )}
              </>
            ) : (
              <>
                {jobs.data?.items.toReversed().map((job) => (
                  <article className="job-card" key={job.id}>
                    <div>
                      <strong>{job.kind.replaceAll('_', ' ')}</strong>
                      <Badge state={job.state} />
                    </div>
                    <p>
                      {job.progress.phase} · {job.progress.completed}
                      {job.progress.total !== null ? ` / ${job.progress.total}` : ''} {job.progress.unit}
                    </p>
                    {job.error && <p className="warning-text">{job.error.message}</p>}
                    <div className="inline-options">
                      {activeStates.includes(job.state) &&
                        !['start_source', 'finalize_source', 'delete_lesson'].includes(job.kind) && (
                          <button onClick={() => void run(() => api(`/jobs/${job.id}/cancel`, 'POST', {}))}>
                            {t('取消任务', 'Cancel task')}
                          </button>
                        )}
                      {['failed', 'cancelled', 'interrupted'].includes(job.state) &&
                        job.kind !== 'start_source' && (
                          <button onClick={() => void run(() => api(`/jobs/${job.id}/retry`, 'POST', {}))}>
                            {t('重试任务', 'Retry task')}
                          </button>
                        )}
                    </div>
                    <small className="muted">{job.id}</small>
                  </article>
                ))}
              </>
            )}
          </aside>
        </div>
      )}
      {recordModal && (
        <Modal title={t('开始一次新录音', 'Start a recording')} onClose={() => setRecordModal(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () => {
                await api<Accepted>(`/lessons/${id}/recordings`, 'POST', {
                  kind,
                  device_id: device,
                  auto_stop_minutes: minutes ? +minutes : null,
                })
                setRecordModal(false)
              })
            }}
          >
            <div className="notice">
              {t(
                '关闭页面不会停止后端录音。请使用“停止采集”结束；音频和相关文本将发送到你配置的云服务。',
                'Closing this tab does not stop recording. Use “Stop capture” to finish. Audio and relevant text are sent to your configured cloud service.',
              )}
            </div>
            <label>
              {t('音频来源', 'Audio input')}
              <Select
                value={kind}
                onChange={(value) => {
                  setKind(value)
                  setDevice('')
                }}
                options={[
                  { value: 'microphone', label: t('麦克风', 'Microphone') },
                  { value: 'loopback', label: t('系统声音', 'System audio') },
                ]}
              />
            </label>
            <label>
              {t('实际设备', 'Actual device')}
              <Select
                required
                value={device}
                onChange={setDevice}
                options={[
                  { value: '', label: t('请选择设备', 'Choose a device') },
                  ...(device && devices.data && !devices.data.devices.some((d) => d.id === device)
                    ? [
                        {
                          value: device,
                          label: t('原设备不可用，请重新选择', 'Previous device unavailable; select again'),
                        },
                      ]
                    : []),
                  ...(devices.data?.devices.map((d) => ({ value: d.id, label: d.label })) ?? []),
                ]}
              />
            </label>
            {devices.data?.unavailable_reason && (
              <p className="warning-text">{devices.data.unavailable_reason}</p>
            )}
            <label>
              {t('自动停止（分钟）', 'Auto stop (minutes)')}
              <input
                type="number"
                min="1"
                max="240"
                list="timer-presets"
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
                placeholder={t('不设倒计时，最长 4 小时', 'No timer, up to 4 hours')}
              />
              <datalist id="timer-presets">
                {[15, 30, 45, 60, 90].map((v) => (
                  <option value={v} key={v} />
                ))}
              </datalist>
            </label>
            <div className="modal-actions">
              <button type="button" onClick={() => setRecordModal(false)}>
                {t('取消', 'Cancel')}
              </button>
              <button
                className="primary"
                disabled={busy || !device || !devices.data?.devices.some((d) => d.id === device)}
              >
                {t('开始录音', 'Start recording')}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {analysisSource && (
        <Modal title={t('分析这份录音', 'Analyze this recording')} onClose={() => setAnalysisSource(null)}>
          <p>
            {analysisSource.original_filename || analysisSource.device_label} ·{' '}
            {duration(analysisSource.duration_ms)}
          </p>
          <p className="muted">
            {t(
              '将使用课堂当前处理方式。已成功识别的音频块不会重复处理。',
              'Uses the current class processing mode. Completed audio chunks will not be processed again.',
            )}
          </p>
          <label>
            {t('处理方式', 'Processing mode')}
            <Select
              value={lesson.automation_mode}
              onChange={(mode) =>
                void run(() => api(`/lessons/${id}/automation`, 'PUT', { mode }, lesson.revision))
              }
              options={[
                { value: 'auto_answer', label: t('自动问答', 'Auto answers') },
                { value: 'detect_only', label: t('仅检测', 'Detect only') },
                { value: 'transcribe_only', label: t('仅转写', 'Transcribe only') },
              ]}
            />
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={autoSummary} onChange={(e) => setAutoSummary(e.target.checked)} />
            {t('完成后自动生成总结', 'Generate a summary when finished')}
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={includeChat} onChange={(e) => setIncludeChat(e.target.checked)} />
            {t('总结包含聊天', 'Include chat in the summary')}
          </label>
          <div className="modal-actions">
            <button onClick={() => setAnalysisSource(null)}>{t('稍后分析', 'Analyze later')}</button>
            <button
              className="primary"
              disabled={busy || !!bootstrap.data?.active_audio}
              onClick={() =>
                void run(async () => {
                  await api(`/sources/${analysisSource.id}/analysis`, 'POST', {
                    generate_summary: autoSummary,
                    include_chat_in_summary: includeChat,
                  })
                  setAnalysisSource(null)
                })
              }
            >
              {t('开始分析', 'Start analysis')}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
