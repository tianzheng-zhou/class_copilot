import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowUpRight, BookOpen, Plus, Search, MoreHorizontal, CalendarDays } from 'lucide-react'
import { api, type Bootstrap, type Course, type Lesson, type Page } from '../api'
import { useUI, useAction, Modal, Empty, Loading, ErrorBox, dateLabel, Badge, Select } from '../ui'

export function Library() {
  const { t, lang } = useUI()
  const { run, busy } = useAction()
  const navigate = useNavigate()
  const [course, setCourse] = useState(''),
    [search, setSearch] = useState(''),
    [from, setFrom] = useState(''),
    [to, setTo] = useState('')
  const [creating, setCreating] = useState(false),
    [selected, setSelected] = useState(''),
    [title, setTitle] = useState(''),
    [courseName, setCourseName] = useState('')
  const [editing, setEditing] = useState<Lesson | null>(null),
    [editTitle, setEditTitle] = useState('')
  const courses = useQuery({ queryKey: ['courses'], queryFn: () => api<Page<Course>>('/courses?limit=200') })
  const bootstrap = useQuery({ queryKey: ['bootstrap'], queryFn: () => api<Bootstrap>('/bootstrap') })
  const filters = new URLSearchParams({
    q: search,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  })
  if (course) filters.set('course_id', course)
  if (from) filters.set('date_from', from)
  if (to) filters.set('date_to', to)
  const lessons = useInfiniteQuery({
    queryKey: ['lessons', filters.toString()],
    initialPageParam: '',
    queryFn: ({ pageParam }) =>
      api<Page<Lesson>>(
        `/lessons?${filters}&limit=24${pageParam ? '&cursor=' + encodeURIComponent(pageParam) : ''}`,
      ),
    getNextPageParam: (p) => p.next_cursor || undefined,
  })
  const items = lessons.data?.pages.flatMap((p) => p.items) || []
  return (
    <div className="page library">
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR LEARNING SPACE</div>
          <h1>{t('每一堂课，都值得留下。', 'Make room for understanding.')}</h1>
          <p>
            {t(
              '从课堂记录到课后思考，在这里继续。',
              'From classroom notes to your next question. Pick up where you left off.',
            )}
          </p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setSelected(course || courses.data?.items[0]?.id || '')
            setCreating(true)
          }}
        >
          <Plus size={18} />
          {t('新建课堂', 'New class')}
        </button>
      </div>
      {!bootstrap.data?.configured && (
        <div className="setup-card">
          <div className="setup-icon">✦</div>
          <div>
            <strong>{t('先连接你的 AI 助手', 'Connect your AI assistant')}</strong>
            <p>
              {t(
                '填写百炼工作空间和 API Key，即可开始转写与问答。课程管理和导出随时可用。',
                'Add your Bailian workspace and API key to transcribe and ask questions. You can organize classes at any time.',
              )}
            </p>
          </div>
          <Link className="button" to="/settings">
            {t('前往设置', 'Set up')}
            <ArrowUpRight size={16} />
          </Link>
        </div>
      )}
      <div className="section-heading">
        <h2>
          {t('课堂记录', 'Your classes')} <span className="count">{lessons.data?.pages[0]?.total || 0}</span>
        </h2>
        <span className="muted">{t('按创建时间排列', 'Newest first')}</span>
      </div>
      <div className="filters">
        <label className="search">
          <Search size={17} />
          <input
            placeholder={t('搜索课堂或课程…', 'Search classes or courses…')}
            aria-label={t('搜索', 'Search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <Select
          aria-label={t('课程筛选', 'Filter course')}
          value={course}
          onChange={setCourse}
          options={[
            { value: '', label: t('全部课程', 'All courses') },
            ...(courses.data?.items.map((c) => ({ value: c.id, label: c.name })) ?? []),
          ]}
        />
        <label className="date-filter">
          <CalendarDays size={16} />
          <input
            type="date"
            aria-label={t('开始日期', 'From date')}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <span>—</span>
          <input
            type="date"
            aria-label={t('结束日期', 'To date')}
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
      </div>
      {lessons.isLoading ? (
        <Loading />
      ) : lessons.isError ? (
        <ErrorBox error={lessons.error} />
      ) : !items.length ? (
        <Empty title={t('你的下一堂课，从这里开始', 'Your next class starts here')}>
          {t(
            '创建一节课堂，录音或导入已有音频。所有内容都会留在同一个工作台。',
            'Create a class, then record or import audio. Everything stays together in one workspace.',
          )}
        </Empty>
      ) : (
        <div className="lesson-grid">
          {items.map((l, index) => (
            <article className="lesson-card" key={l.id}>
              <div className="card-top">
                <span className={`course-icon color-${index % 4}`}>
                  <BookOpen size={21} />
                </span>
                <button
                  className="icon-button"
                  aria-label={t('课堂操作', 'Class actions')}
                  onClick={() => {
                    setEditing(l)
                    setEditTitle(l.custom_title || '')
                  }}
                >
                  <MoreHorizontal size={19} />
                </button>
              </div>
              <span className="course-tag">{l.course_name}</span>
              <Link to={`/lessons/${l.id}`}>
                <h3>{l.custom_title || `${l.course_name} · ${dateLabel(l.created_at, lang)}`}</h3>
              </Link>
              <div className="card-meta">
                {dateLabel(l.created_at, lang)} {l.lifecycle !== 'ready' && <Badge state={l.lifecycle} />}
              </div>
              <div className="card-footer">
                <span>
                  {l.transcript_count} {t('片段', 'segments')}
                  <i /> {l.question_count} {t('问题', 'questions')}
                </span>
                <Link to={`/lessons/${l.id}`} aria-label={t('打开课堂', 'Open class')}>
                  <ArrowUpRight size={18} />
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
      {lessons.hasNextPage && (
        <button className="load-more" onClick={() => void lessons.fetchNextPage()}>
          {t('加载更多课堂', 'Load more classes')}
        </button>
      )}
      {creating && (
        <Modal title={t('新建课堂', 'New class')} onClose={() => setCreating(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () => {
                let courseId = selected
                if (!courseId) {
                  const c = await api<Course>('/courses', 'POST', { name: courseName })
                  courseId = c.id
                }
                const l = await api<Lesson>('/lessons', 'POST', {
                  course_id: courseId,
                  custom_title: title.trim() || null,
                })
                setCreating(false)
                navigate(`/lessons/${l.id}`)
              })
            }}
          >
            <label>
              {t('所属课程', 'Course')}
              <Select
                value={selected}
                onChange={setSelected}
                options={[
                  { value: '', label: `＋ ${t('创建新课程', 'Create course')}` },
                  ...(courses.data?.items.map((c) => ({ value: c.id, label: c.name })) ?? []),
                ]}
              />
            </label>
            {!selected && (
              <label>
                {t('新课程名称', 'New course name')}
                <input
                  autoFocus
                  required
                  maxLength={100}
                  value={courseName}
                  onChange={(e) => setCourseName(e.target.value)}
                  placeholder={t('例如：线性代数', 'e.g. Linear algebra')}
                />
              </label>
            )}
            <label>
              {t('课堂名称（选填）', 'Class title (optional)')}
              <input
                maxLength={200}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('留空使用课程名称和时间', 'Leave blank to use course and date')}
              />
            </label>
            <div className="modal-actions">
              <button type="button" onClick={() => setCreating(false)}>
                {t('取消', 'Cancel')}
              </button>
              <button className="primary" disabled={busy}>
                {t('创建课堂', 'Create class')}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {editing && (
        <Modal title={t('管理课堂', 'Manage class')} onClose={() => setEditing(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () => {
                await api(
                  `/lessons/${editing.id}`,
                  'PATCH',
                  { custom_title: editTitle.trim() || null },
                  editing.revision,
                )
                setEditing(null)
              })
            }}
          >
            <label>
              {t('课堂名称', 'Class title')}
              <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} maxLength={200} />
            </label>
            <p className="muted">{t('留空可恢复默认名称。', 'Leave blank to restore the default title.')}</p>
            <div className="modal-actions">
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => {
                  if (
                    confirm(
                      t(
                        '将删除此课堂的全部文字、答案版本、聊天、总结和音频。确定删除？',
                        'Delete this class and all transcripts, answer versions, chats, summaries and audio?',
                      ),
                    )
                  )
                    void run(async () => {
                      await api(`/lessons/${editing.id}`, 'DELETE')
                      setEditing(null)
                    })
                }}
              >
                {t('删除课堂', 'Delete class')}
              </button>
              <button className="primary" disabled={busy}>
                {t('保存', 'Save')}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
