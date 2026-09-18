import { useContext, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useBlocker } from 'react-router-dom'
import { Check, KeyRound, Mic, Plus, RefreshCw, Save, Settings2, Trash2 } from 'lucide-react'
import { api, type Accepted, type Course, type Device, type Job, type Page, type Settings } from '../api'
import { Badge, Empty, ErrorBox, Loading, Modal, useAction, useUI } from '../ui'
import { LiveContext } from '../main'

type PublicSettings = Settings & { revision: number; id: string; effective: Record<string, string> }
type Credential = { set: boolean; masked_value: string | null; revision: number }
const fields = [
  'provider',
  'models',
  'transcription',
  'automation',
  'detection',
  'generation',
  'audio',
] as const
function configOnly(value: PublicSettings): Settings {
  return Object.fromEntries(fields.map((k) => [k, value[k]])) as Settings
}
export function SettingsPage() {
  const { t, notify } = useUI()
  const { run, busy } = useAction()
  const live = useContext(LiveContext)
  const query = useQuery({ queryKey: ['settings'], queryFn: () => api<PublicSettings>('/settings') })
  const credential = useQuery({
    queryKey: ['credential'],
    queryFn: () => api<Credential>('/providers/dashscope/credential'),
  })
  const courses = useQuery({ queryKey: ['courses'], queryFn: () => api<Page<Course>>('/courses?limit=200') })
  const [form, setForm] = useState<Settings | null>(null),
    [revision, setRevision] = useState(0),
    [saved, setSaved] = useState(''),
    [key, setKey] = useState(''),
    [showKey, setShowKey] = useState(false),
    [name, setName] = useState(''),
    [editing, setEditing] = useState<Course | null>(null),
    [rename, setRename] = useState(''),
    [testJob, setTestJob] = useState<string | null>(null)
  const dirty = !!form && JSON.stringify(form) !== saved
  const blocker = useBlocker(dirty || !!key)
  useEffect(() => {
    if (query.data && !form) {
      const settings = configOnly(query.data)
      setForm(settings)
      setSaved(JSON.stringify(settings))
      setRevision(query.data.revision)
    }
  }, [query.data, form])
  useEffect(() => {
    if (!dirty && !key) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty, key])
  const devices = useQuery({
    queryKey: ['devices', form?.audio.default_kind],
    queryFn: () =>
      api<{ devices: Device[]; unavailable_reason: string | null }>(
        `/audio/devices?kind=${form!.audio.default_kind}`,
      ),
    enabled: !!form,
  })
  const test = useQuery({
    queryKey: ['job', testJob],
    queryFn: () => api<Job>(`/jobs/${testJob}`),
    enabled: !!testJob,
    refetchInterval: (q) =>
      ['queued', 'running', 'cancelling'].includes(q.state.data?.state || 'queued') ? 500 : false,
  })
  const set = <K extends keyof Settings>(group: K, field: keyof Settings[K], value: unknown) =>
    setForm((old) => (old ? { ...old, [group]: { ...old[group], [field]: value } } : old))
  if (query.isLoading || !form) return <Loading />
  if (query.isError) return <ErrorBox error={query.error} />
  const modelFields: [keyof Settings['models'], string, string][] = [
    ['transcription', '语音转写', 'Transcription'],
    ['detection', '问题检测', 'Question detection'],
    ['answer', '参考答案', 'Answers'],
    ['chat_fast', '快速聊天', 'Fast chat'],
    ['chat_quality', '质量聊天', 'Quality chat'],
    ['summary', '课堂总结', 'Summaries'],
  ]
  return (
    <div className="page settings-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">MAKE IT YOURS</div>
          <h1>{t('设置与课程', 'Settings & courses')}</h1>
          <p>
            {t(
              '连接你的服务，选择适合自己的课堂方式。',
              'Connect your service and make this workspace your own.',
            )}
          </p>
        </div>
        <div className="inline-options">
          <button
            disabled={!dirty || busy}
            onClick={() => {
              if (query.data) {
                const settings = configOnly(query.data)
                setForm(settings)
                setSaved(JSON.stringify(settings))
                setRevision(query.data.revision)
              }
            }}
          >
            {t('取消更改', 'Discard changes')}
          </button>
          <button
            className="primary"
            disabled={!dirty || busy}
            onClick={() =>
              void run(
                async () => {
                  const updated = await api<PublicSettings>('/settings', 'PATCH', form, revision)
                  const settings = configOnly(updated)
                  setForm(settings)
                  setSaved(JSON.stringify(settings))
                  setRevision(updated.revision)
                },
                t('设置已保存', 'Settings saved'),
              )
            }
          >
            <Save size={17} />
            {t('保存设置', 'Save settings')}
          </button>
        </div>
      </div>
      {dirty && (
        <div className="notice">
          {t(
            '有未保存的设置。音频设置在下一来源生效；生成设置在下一任务生效。',
            'You have unsaved changes. Audio settings apply to the next source; generation settings apply to the next task.',
          )}
        </div>
      )}
      {query.data && query.data.revision !== revision && (
        <div className="notice error">
          {t(
            '设置已在其他页面修改。请取消当前更改、加载最新设置后重新编辑。',
            'Settings changed in another tab. Discard these changes and edit the latest version.',
          )}
        </div>
      )}
      <section className="settings-section">
        <div className="settings-section-title">
          <KeyRound size={20} />
          <div>
            <h2>{t('连接 AI 服务', 'Connect AI service')}</h2>
            <p>
              {t(
                '音频和相关课堂文本将发送到所选百炼服务，课堂记录保存在本机。',
                'Audio and relevant classroom text are sent to Bailian. Your records remain on this computer.',
              )}
            </p>
          </div>
        </div>
        <div className="form-grid">
          <label>
            {t('工作空间区域', 'Workspace region')}
            <select value={form.provider.region} onChange={(e) => set('provider', 'region', e.target.value)}>
              <option value="">{t('请选择实际区域', 'Select your actual region')}</option>
              {[
                'cn-beijing',
                'ap-southeast-1',
                'cn-hongkong',
                'ap-northeast-1',
                'eu-central-1',
                'us-east-1',
              ].map((region) => (
                <option key={region}>{region}</option>
              ))}
            </select>
          </label>
          <label>
            {t('工作空间兼容地址', 'Workspace compatible URL')}
            <input
              type="url"
              placeholder="https://…maas.aliyuncs.com/compatible-mode/v1"
              value={form.provider.base_url}
              onChange={(e) => set('provider', 'base_url', e.target.value)}
            />
          </label>
        </div>
        <p className="muted">
          {t(
            '从百炼控制台复制与你的 Key 和区域对应的服务地址；不会根据电脑所在地自动选择。',
            'Copy the service URL matching your key and region from the Bailian console.',
          )}
        </p>
        <div className="credential-section">
          <div className="section-heading">
            <strong>API Key</strong>
            <span className="credential-status">
              {credential.data?.set ? (
                <>
                  <Check size={14} />
                  {t('已保存', 'Saved')} {credential.data.masked_value}
                </>
              ) : (
                t('尚未配置', 'Not configured')
              )}
            </span>
          </div>
          <div className="key-input">
            <input
              type={showKey ? 'text' : 'password'}
              value={key}
              autoComplete="off"
              placeholder={t('输入新 Key 以保存或替换', 'Enter a new API key')}
              onChange={(e) => setKey(e.target.value)}
              aria-label="API Key"
            />
            <button onClick={() => setShowKey(!showKey)}>
              {showKey ? t('隐藏', 'Hide') : t('显示', 'Show')}
            </button>
          </div>
          <div className="inline-options">
            <button
              disabled={!key.trim() || busy}
              onClick={() =>
                void run(
                  async () => {
                    await api(
                      '/providers/dashscope/credential',
                      'PUT',
                      { api_key: key.trim() },
                      credential.data?.revision,
                    )
                    setKey('')
                  },
                  t('Key 已保存，尚未调用模型', 'Key saved. No model request was made.'),
                )
              }
            >
              {t('单独保存 Key', 'Save key')}
            </button>
            <button disabled={!key} onClick={() => setKey('')}>
              {t('取消', 'Cancel')}
            </button>
            <button
              className="danger text-button"
              disabled={!credential.data?.set || busy}
              onClick={() => {
                if (confirm(t('清除已保存的 API Key？', 'Clear the saved API key?')))
                  void run(() => api('/providers/dashscope/credential', 'DELETE'))
              }}
            >
              {t('清除 Key', 'Clear key')}
            </button>
          </div>
        </div>
        <div className="connection-tests">
          <p>
            {t(
              '连接测试会调用已保存配置中的模型，可能产生费用。使用内置小样本，不读取旧录音。',
              'Connection tests call the saved model configuration and may incur charges. They use a built-in sample.',
            )}
          </p>
          <div className="inline-options">
            {['text', 'transcription'].map((capability) => (
              <button
                key={capability}
                disabled={busy || dirty || !credential.data?.set}
                onClick={() =>
                  void run(async () => {
                    const result = await api<Accepted>('/providers/dashscope/tests', 'POST', { capability })
                    setTestJob(result.job.id)
                  })
                }
              >
                {capability === 'text'
                  ? t('测试文本模型', 'Test text model')
                  : t('测试语音模型', 'Test audio model')}
              </button>
            ))}
          </div>
        </div>
      </section>
      <section className="settings-section">
        <div className="settings-section-title">
          <Mic size={20} />
          <div>
            <h2>{t('音源与录音', 'Audio & recording')}</h2>
            <p>
              {t(
                '选择实际输入设备；下次录音生效。',
                'Choose the actual input device. Applies to the next recording.',
              )}
            </p>
          </div>
        </div>
        <div className="form-grid">
          <label>
            {t('默认音源', 'Default input')}
            <select
              value={form.audio.default_kind}
              onChange={(e) => {
                set('audio', 'default_kind', e.target.value)
                set('audio', 'default_device_id', null)
              }}
            >
              <option value="microphone">{t('麦克风', 'Microphone')}</option>
              <option value="loopback">{t('系统声音', 'System audio')}</option>
            </select>
          </label>
          <label>
            {t('默认设备', 'Default device')}
            <select
              value={form.audio.default_device_id || ''}
              onChange={(e) => set('audio', 'default_device_id', e.target.value || null)}
            >
              <option value="">
                {t('系统默认（开始前解析具体设备）', 'System default (resolved before recording)')}
              </option>
              {form.audio.default_device_id &&
                !devices.data?.devices.some((d) => d.id === form.audio.default_device_id) && (
                  <option value={form.audio.default_device_id}>
                    {t('原设备已不可用，请重新选择', 'Previous device unavailable; choose again')}
                  </option>
                )}
              {devices.data?.devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('自动停止分钟数', 'Auto stop minutes')}
            <input
              type="number"
              min="1"
              max="240"
              value={form.audio.auto_stop_minutes || ''}
              placeholder={t('不设倒计时', 'No timer')}
              onChange={(e) => set('audio', 'auto_stop_minutes', e.target.value ? +e.target.value : null)}
            />
          </label>
          <label>
            {t('识别语言', 'Speech language')}
            <select
              value={form.transcription.language}
              onChange={(e) => set('transcription', 'language', e.target.value)}
            >
              <option value="mixed">{t('中英混合，保留原语种', 'Mixed, preserve original language')}</option>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </label>
        </div>
        {devices.data?.unavailable_reason && (
          <p className="warning-text">{devices.data.unavailable_reason}</p>
        )}
        <div className="inline-options">
          <button onClick={() => void devices.refetch()}>
            <RefreshCw size={15} />
            {t('刷新设备', 'Refresh devices')}
          </button>
          <button
            disabled={busy || !devices.data?.devices.length}
            onClick={() =>
              void run(async () => {
                const deviceId =
                  form.audio.default_device_id ||
                  devices.data?.devices.find((d) => d.is_default)?.id ||
                  devices.data?.devices[0]?.id
                if (!deviceId) {
                  notify(t('请选择设备', 'Choose a device'), true)
                  return
                }
                const result = await api<Accepted>('/audio/tests', 'POST', {
                  kind: form.audio.default_kind,
                  device_id: deviceId,
                })
                setTestJob(result.job.id)
              })
            }
          >
            {t('测试此音源 5 秒', 'Test this input for 5 seconds')}
          </button>
        </div>
      </section>
      <section className="settings-section">
        <div className="settings-section-title">
          <Settings2 size={20} />
          <div>
            <h2>{t('模型与生成偏好', 'Models & generation')}</h2>
            <p>
              {t(
                '已保存的历史答案不会因切换偏好而隐藏。',
                'Changing defaults never hides your existing answers.',
              )}
            </p>
          </div>
        </div>
        <div className="form-grid">
          {modelFields.map(([field, zh, en]) => (
            <label key={field}>
              {t(zh, en)}
              <select
                value={form.models[field]}
                disabled={field === 'transcription'}
                onChange={(e) => set('models', field, e.target.value)}
              >
                {(field === 'transcription' ? ['qwen3.8-omni-flash'] : ['qwen3.8-flash', 'qwen3.8-max']).map(
                  (model) => (
                    <option key={model}>{model}</option>
                  ),
                )}
              </select>
            </label>
          ))}
          <label>
            {t('生成语言', 'Generated content language')}
            <select
              value={form.generation.language}
              onChange={(e) => set('generation', 'language', e.target.value)}
            >
              <option value="zh">中文</option>
              <option value="en">English</option>
              <option value="bilingual">{t('中英双语', 'Bilingual')}</option>
            </select>
          </label>
          <label>
            {t('默认答案样式', 'Default answer style')}
            <select
              value={form.generation.default_style}
              onChange={(e) => set('generation', 'default_style', e.target.value)}
            >
              <option value="brief">{t('简要', 'Brief')}</option>
              <option value="detailed">{t('详细', 'Detailed')}</option>
            </select>
          </label>
          <label>
            {t('新课堂默认处理方式', 'New class processing mode')}
            <select
              value={form.automation.default_mode}
              onChange={(e) => set('automation', 'default_mode', e.target.value)}
            >
              <option value="auto_answer">{t('自动问答', 'Auto answers')}</option>
              <option value="detect_only">{t('仅检测', 'Detect only')}</option>
              <option value="transcribe_only">{t('仅转写', 'Transcribe only')}</option>
            </select>
          </label>
        </div>
        <details className="advanced">
          <summary>{t('高级参数', 'Advanced settings')}</summary>
          <div className="form-grid">
            {(
              [
                ['transcription', 'max_chunk_seconds', '最长音频块（秒）', 'Max chunk seconds', 4, 30, 1],
                ['transcription', 'silence_ms', '静音分段（毫秒）', 'Silence boundary (ms)', 200, 2000, 100],
                ['detection', 'confidence_threshold', '问题置信度', 'Question confidence', 0, 1, 0.05],
                ['detection', 'cooldown_seconds', '自动检测冷却（秒）', 'Detection cooldown (s)', 0, 120, 1],
                [
                  'detection',
                  'dedup_window_seconds',
                  '相似问题抑制窗口（秒）',
                  'Similar question window (s)',
                  0,
                  3600,
                  1,
                ],
              ] as const
            ).map(([group, field, zh, en, min, max, step]) => (
              <label key={field}>
                {t(zh, en)}
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={(form[group] as unknown as Record<string, number>)[field]}
                  onChange={(e) =>
                    setForm((old) =>
                      old ? { ...old, [group]: { ...old[group], [field]: +e.target.value } } : old,
                    )
                  }
                />
              </label>
            ))}
          </div>
        </details>
      </section>
      <section className="settings-section">
        <div className="settings-section-title">
          <h2>{t('课程管理', 'Courses')}</h2>
        </div>
        <form
          className="new-course"
          onSubmit={(e) => {
            e.preventDefault()
            void run(async () => {
              await api('/courses', 'POST', { name: name.trim() })
              setName('')
            })
          }}
        >
          <input
            required
            maxLength={100}
            placeholder={t('新课程名称', 'New course name')}
            aria-label={t('新课程名称', 'New course name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button disabled={busy || !name.trim()}>
            <Plus size={16} />
            {t('创建课程', 'Create course')}
          </button>
        </form>
        {courses.data?.items.length ? (
          <div className="course-table">
            {courses.data.items.map((course) => (
              <div key={course.id}>
                <div>
                  <strong>{course.name}</strong>
                  <small>
                    {course.lesson_count} {t('节课堂', 'classes')}
                  </small>
                </div>
                <button
                  onClick={() => {
                    setEditing(course)
                    setRename(course.name)
                  }}
                >
                  {t('重命名', 'Rename')}
                </button>
                <button
                  className="icon-button danger"
                  disabled={busy || !!course.lesson_count}
                  aria-label={t('删除空课程', 'Delete empty course')}
                  onClick={() => {
                    if (confirm(t('删除这个空课程？', 'Delete this empty course?')))
                      void run(() => api(`/courses/${course.id}`, 'DELETE'))
                  }}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <Empty title={t('还没有课程', 'No courses yet')} />
        )}
      </section>
      {editing && (
        <Modal title={t('重命名课程', 'Rename course')} onClose={() => setEditing(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () => {
                await api(`/courses/${editing.id}`, 'PATCH', { name: rename.trim() }, editing.revision)
                setEditing(null)
              })
            }}
          >
            <input
              required
              autoFocus
              maxLength={100}
              value={rename}
              onChange={(e) => setRename(e.target.value)}
              aria-label={t('课程名称', 'Course name')}
            />
            <div className="modal-actions">
              <button type="button" onClick={() => setEditing(null)}>
                {t('取消', 'Cancel')}
              </button>
              <button className="primary" disabled={busy}>
                {t('保存', 'Save')}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {testJob && (
        <Modal title={t('测试结果', 'Test result')} onClose={() => setTestJob(null)}>
          {test.data ? (
            <>
              <Badge state={test.data.state} />
              <p>
                {test.data.progress.phase}
                {test.data.progress.latency_ms ? ` · ${test.data.progress.latency_ms} ms` : ''}
              </p>
              {live[testJob]?.db !== undefined && (
                <meter min="-100" max="0" value={live[testJob].db} aria-label={t('测试音量', 'Test level')} />
              )}
              {test.data.error && <p className="warning-text">{test.data.error.message}</p>}
              {['queued', 'running'].includes(test.data.state) && (
                <button onClick={() => void run(() => api(`/jobs/${testJob}/cancel`, 'POST', {}))}>
                  {t('取消测试', 'Cancel test')}
                </button>
              )}
            </>
          ) : (
            <Loading />
          )}
        </Modal>
      )}
      {blocker.state === 'blocked' && (
        <Modal title={t('有未保存的更改', 'Unsaved changes')} onClose={() => blocker.reset()}>
          <p>
            {t(
              '离开会丢弃当前未保存的设置和 Key 输入。',
              'Leaving will discard unsaved settings and key input.',
            )}
          </p>
          <div className="modal-actions">
            <button onClick={() => blocker.reset()}>{t('继续编辑', 'Keep editing')}</button>
            <button className="danger" onClick={() => blocker.proceed()}>
              {t('放弃并离开', 'Discard and leave')}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
