import { describe, expect, it, vi } from 'vitest'
import { api, mergeEntities, setCsrf } from '../src/api'

describe('event recovery and command identity', () => {
  it('replaces newer checkpoints and ignores replayed older revisions', () => {
    expect(
      mergeEntities(
        [{ id: 'a', revision: 4, content: 'saved' }],
        [
          { id: 'a', revision: 3, content: 'old' },
          { id: 'b', revision: 1, content: 'new' },
        ],
      ),
    ).toEqual([
      { id: 'a', revision: 4, content: 'saved' },
      { id: 'b', revision: 1, content: 'new' },
    ])
    expect(
      mergeEntities(
        [{ id: 'a', revision: 4, content: 'first' }],
        [{ id: 'a', revision: 5, content: 'whole text' }],
      ),
    ).toEqual([{ id: 'a', revision: 5, content: 'whole text' }])
  })
  it('queries the same command after an uncertain POST and never invents a new command', async () => {
    vi.stubGlobal('navigator', { onLine: true })
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('network'))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: { response_body: { id: 'saved' } } }),
      })
    vi.stubGlobal('fetch', fetch)
    setCsrf('csrf')
    expect(await api('/courses', 'POST', { name: 'A' }, undefined, 'known-key')).toEqual({ id: 'saved' })
    expect(fetch.mock.calls[1][0]).toBe('/api/v1/commands/known-key')
    expect(fetch).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
  })
})
