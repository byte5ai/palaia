import '@testing-library/jest-dom/vitest'

import { FakeEventSource } from './lib/testEventSource'

// jsdom implements no EventSource at all — every component that reaches
// AppShell (which opens the live-state SSE stream) would otherwise throw
// a ReferenceError in every test. Individual tests that need to control
// events still pass their own FakeEventSource instance to useEventStream.
if (typeof globalThis.EventSource === 'undefined') {
  // @ts-expect-error - a deliberately partial stand-in, see testEventSource.ts
  globalThis.EventSource = FakeEventSource
}
