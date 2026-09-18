import type { components } from './api.generated'
export type Course = components['schemas']['Course']
export type Lesson = components['schemas']['Lesson']
export type Source = components['schemas']['Source']
export type Transcript = components['schemas']['Transcript']
export type Question = components['schemas']['Question']
export type Answer = components['schemas']['Answer']
export type ChatTurn = components['schemas']['ChatTurn']
export type Summary = components['schemas']['Summary']
export type Job = components['schemas']['Job']
type RequiredDeep<T> = T extends object ? { [K in keyof T]-?: RequiredDeep<T[K]> } : T
export type Settings = RequiredDeep<components['schemas']['Settings']>
export type Page<T> = { items: T[]; next_cursor: string | null; total: number }
export type Bootstrap = {
  csrf_token: string
  configured: boolean
  active_audio: Job | null
  event_cursor: string
  capabilities: Record<string, { thinking: boolean }>
}
export type Snapshot = {
  lesson: Lesson
  sources: Page<Source>
  transcripts: Page<Transcript>
  questions: Page<Question>
  chat_turns: Page<ChatTurn>
  summaries: Page<Summary>
  active_jobs: Job[]
  event_cursor: string
}
export type Accepted = { job: Job; resource: { type: string; id: string } | null }
export type Device = { id: string; label: string; kind: string; is_default?: boolean }
let csrf = ''
export function setCsrf(value: string) {
  csrf = value
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message)
  }
}
export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  revision?: number,
  key?: string,
): Promise<T> {
  if (method !== 'GET' && !navigator.onLine) throw new ApiError('offline', '连接已断开，请恢复连接后重试')
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf
  if (method === 'POST' || method === 'DELETE') headers['Idempotency-Key'] = key || crypto.randomUUID()
  if (revision !== undefined) headers['If-Match'] = `"${revision}"`
  let response: Response
  try {
    response = await fetch('/api/v1' + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    if (headers['Idempotency-Key']) {
      try {
        const result = await api<{ response_body: T }>(`/commands/${headers['Idempotency-Key']}`)
        return result.response_body
      } catch {
        /* An absent/expired command is not proof of non-execution. */
      }
    }
    throw new ApiError('outcome_unknown', '请求结果尚未确认，请刷新状态后再操作')
  }
  if (response.status === 204) return undefined as T
  const result = await response.json()
  if (!response.ok)
    throw new ApiError(
      result.error?.code || 'request_failed',
      result.error?.message || '请求失败',
      result.error?.details,
    )
  return result.data as T
}
export function upload(lesson: string, file: File, onProgress: (percent: number) => void) {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<Source>((resolve, reject) => {
    xhr.open('POST', `/api/v1/lessons/${lesson}/uploads`)
    xhr.setRequestHeader('X-CSRF-Token', csrf)
    xhr.setRequestHeader('Idempotency-Key', crypto.randomUUID())
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      try {
        const result = JSON.parse(xhr.responseText)
        if (xhr.status >= 400)
          reject(new ApiError(result.error.code, result.error.message, result.error.details))
        else resolve(result.data)
      } catch {
        reject(new ApiError('request_failed', '上传失败'))
      }
    }
    xhr.onerror = () => reject(new ApiError('outcome_unknown', '上传结果未知，请刷新音源列表'))
    xhr.onabort = () => reject(new ApiError('cancelled', '上传已取消'))
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
  return { promise, cancel: () => xhr.abort() }
}
export function mergeEntities<T extends { id: string; revision: number }>(old: T[], next: T[]) {
  const map = new Map(old.map((x) => [x.id, x]))
  for (const item of next)
    if (!map.has(item.id) || map.get(item.id)!.revision <= item.revision) map.set(item.id, item)
  return [...map.values()]
}
