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

  it('increments the vault-change count on each vault_changed event — the badge that must update without reload', async () => {
    const { result } = renderHook(() => useEventStream(FakeEventSource as unknown as typeof EventSource))
    const source = FakeEventSource.instances.at(-1)!

    act(() => {
      source.emit('vault_changed', { data: { count: 1, paths: ['note.md'] } })
    })
    await waitFor(() => expect(result.current.vaultChangeCount).toBe(1))

    act(() => {
      source.emit('vault_changed', { data: { count: 2, paths: ['a.md', 'b.md'] } })
    })
    await waitFor(() => expect(result.current.vaultChangeCount).toBe(3))
    expect(result.current.lastVaultChange).toEqual({ count: 2, paths: ['a.md', 'b.md'] })
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
