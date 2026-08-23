/**
 * A controllable stand-in for the browser's `EventSource`, used by tests
 * and Ladle stories that need `useEventStream` (./events.ts) to behave
 * deterministically instead of opening a real connection. jsdom does not
 * implement `EventSource` at all, so this also serves as the global
 * fallback in `setupTests.ts` — without it, any component that reaches
 * `AppShell` would throw a `ReferenceError` in every test.
 */
export class FakeEventSource implements Pick<EventSource, "close" | "url"> {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  private listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.closed = true;
  }

  /** Test/story helper: dispatch a named SSE event with a JSON-encoded
   * `data` payload, matching the SPEC-201 envelope shape the hub sends. */
  emit(
    type:
      | "health"
      | "memory.entry.created"
      | "memory.entry.updated"
      | "memory.entry.deleted"
      | "memory.entry.moved"
      | "open"
      | "error",
    data?: unknown,
  ): void {
    const event = { data: data === undefined ? "" : JSON.stringify(data) } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}
