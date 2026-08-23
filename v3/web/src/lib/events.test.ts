import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useEventStream } from './events'
import { FakeEventSource } from './testEventSource'

describe('useEventStream', () => {
  it('reflects an immediate health snapshot and marks the connection open', async () => {
    const { result } = renderHook(() => useEventStream(FakeEventSource as unknown as typeof EventSource))
    const source = FakeEventSource.instances.at(-1)!

    act(() => {
      source.emit('open')
      source.emit('health', { data: { status: 'ok' }, ts: Date.now() / 1000 })
    })

    await waitFor(() => expect(result.current.connection).toBe('open'))
    expect(result.current.health).toEqual({ status: 'ok' })
  })

  it('increments the vault-change count on each memory.entry.* event — the badge that must update without reload', async () => {
    const { result } = renderHook(() => useEventStream(FakeEventSource as unknown as typeof EventSource))
    const source = FakeEventSource.instances.at(-1)!

    act(() => {
      source.emit('memory.entry.created', {
        event: 'memory.entry.created',
        vault: 'work',
        permalink: 'note',
        data: { path: 'note.md' },
      })
    })
    await waitFor(() => expect(result.current.vaultChangeCount).toBe(1))

    act(() => {
      source.emit('memory.entry.updated', {
        event: 'memory.entry.updated',
        vault: 'work',
        permalink: 'a',
        data: { path: 'a.md' },
      })
    })
    await waitFor(() => expect(result.current.vaultChangeCount).toBe(2))
    expect(result.current.lastVaultChange).toMatchObject({
      event: 'memory.entry.updated',
      vault: 'work',
      permalink: 'a',
      data: { path: 'a.md' },
    })
  })

  it('keeps a bounded, newest-first history of memory.entry.* events for the activity feed', async () => {
    const { result } = renderHook(() => useEventStream(FakeEventSource as unknown as typeof EventSource))
    const source = FakeEventSource.instances.at(-1)!

    act(() => {
      source.emit('memory.entry.created', {
        event: 'memory.entry.created',
        vault: 'work',
        permalink: 'note',
        data: { path: 'note.md' },
      })
    })
    await waitFor(() => expect(result.current.recentChanges).toHaveLength(1))

    act(() => {
      source.emit('memory.entry.deleted', {
        event: 'memory.entry.deleted',
        vault: 'work',
        permalink: 'a',
        data: { path: 'a.md' },
      })
    })
    await waitFor(() => expect(result.current.recentChanges).toHaveLength(2))
    expect(result.current.recentChanges[0]).toMatchObject({
      event: 'memory.entry.deleted',
      data: { path: 'a.md' },
    })
    expect(result.current.recentChanges[1]).toMatchObject({
      event: 'memory.entry.created',
      data: { path: 'note.md' },
    })
  })

  it('reports reconnecting after a drop that follows a successful connection', async () => {
    const { result } = renderHook(() => useEventStream(FakeEventSource as unknown as typeof EventSource))
    const source = FakeEventSource.instances.at(-1)!

    act(() => {
      source.emit('open')
    })
    await waitFor(() => expect(result.current.connection).toBe('open'))

    act(() => {
      source.emit('error')
    })
    await waitFor(() => expect(result.current.connection).toBe('reconnecting'))
  })

  it('closes the underlying source on unmount', () => {
    const { unmount } = renderHook(() =>
      useEventStream(FakeEventSource as unknown as typeof EventSource),
    )
    const source = FakeEventSource.instances.at(-1)!

    unmount()

    expect(source.closed).toBe(true)
  })
})
