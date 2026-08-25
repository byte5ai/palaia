import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { EnvelopeMetadata, SessionListResult, SessionRecord } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { EventStreamState } from "../lib/events";
import { useEventStream } from "../lib/events";
import { FakeEventSource } from "../lib/testEventSource";
import { Agents } from "./Agents";

const ACTIVE_SESSION: SessionRecord = {
  handle: "abc123handle",
  scope: "refactoring billing",
  host: "laptop",
  platform: "claude-code",
  agent_kind: "coding assistant",
  model: "sonnet-5",
  status: "active",
  capabilities: [],
  registered_at: 1_000,
  last_seen_at: Date.now() / 1000,
  ttl_seconds: 300,
};

const STALE_SESSION: SessionRecord = {
  ...ACTIVE_SESSION,
  handle: "stalehandle999",
  scope: "gone quiet",
  status: "stale",
};

const A_FLOW: EnvelopeMetadata = {
  id: "env-1",
  type: "request",
  from: "abc123handle",
  to: "def456handle",
  recipient: "def456handle",
  subject: "please rename the model",
  urgency: "high",
  expects_reply: true,
  refs: [],
  reply_to: null,
  created_at: 1_000,
  expires_at: 90_000,
  state: "pending",
  body_bytes: 10,
};

const BASE_STREAM: EventStreamState = {
  connection: "open",
  health: null,
  healthAt: null,
  vaultChangeCount: 0,
  lastVaultChange: null,
  recentChanges: [],
  agentActivityCount: 0,
};

function StaticShell({ stream }: { stream: EventStreamState }) {
  return <Outlet context={stream} />;
}

function mount(stream: EventStreamState = BASE_STREAM) {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <StaticShell stream={stream} />,
        children: [{ index: true, element: <Agents /> }],
      },
    ],
    { initialEntries: ["/"] },
  );
  return render(
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>,
  );
}

/** A harness that runs the real `useEventStream` hook against a
 * `FakeEventSource`, so a test can fire a genuine SSE frame and assert the
 * Agents screen reacts to it — the SPEC-405 acceptance criterion's own
 * words: "renders live updates from real session.* events (vitest with
 * SSE fixture)". */
function LiveShell() {
  const stream = useEventStream(FakeEventSource as unknown as typeof EventSource);
  return <Outlet context={stream} />;
}

function mountLive() {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <LiveShell />,
        children: [{ index: true, element: <Agents /> }],
      },
    ],
    { initialEntries: ["/"] },
  );
  return render(
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  FakeEventSource.instances.length = 0;
});

describe("Agents screen", () => {
  it("renders the directory with a stale agent visibly distinct", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({
      sessions: [ACTIVE_SESSION, STALE_SESSION],
    });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [] });

    mount();

    await screen.findByText(ACTIVE_SESSION.handle);
    expect(screen.getByText(STALE_SESSION.handle)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    // "stale" is never shown verbatim — the plain-language label is what a
    // person reads (system.md §3 rule 0).
    expect(screen.getByText("Inactive")).toBeInTheDocument();
    expect(screen.queryByText(/\bstale\b/i)).not.toBeInTheDocument();
  });

  it("renders a live update from a real session.* event (SSE fixture)", async () => {
    const listSessions = vi
      .spyOn(api, "listSessions")
      .mockResolvedValueOnce({ sessions: [] } satisfies SessionListResult)
      .mockResolvedValueOnce({ sessions: [ACTIVE_SESSION] } satisfies SessionListResult);
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [] });

    mountLive();
    await screen.findByText(/No agents yet/i);
    expect(listSessions).toHaveBeenCalledTimes(1);

    const source = FakeEventSource.instances.at(-1)!;
    act(() => {
      source.emit("session.registered", {
        event: "session.registered",
        data: { handle: ACTIVE_SESSION.handle },
      });
    });

    await waitFor(() => expect(listSessions).toHaveBeenCalledTimes(2));
    await screen.findByText(ACTIVE_SESSION.handle);
  });

  it("lists message flows and expands a body only on click", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({ sessions: [ACTIVE_SESSION] });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [A_FLOW] });
    const detail = vi.spyOn(api, "envelopeDetail").mockResolvedValue({
      item: {
        envelope: {
          id: A_FLOW.id,
          type: A_FLOW.type,
          from: A_FLOW.from,
          to: A_FLOW.to,
          subject: A_FLOW.subject,
          urgency: A_FLOW.urgency,
          expects_reply: A_FLOW.expects_reply,
          body: "the actual message text",
          refs: [],
          reply_to: null,
          created_at: A_FLOW.created_at,
          expires_at: A_FLOW.expires_at,
        },
        recipient: A_FLOW.recipient,
        state: A_FLOW.state,
        delivered_at: null,
        acked_at: null,
      },
    });

    mount();
    await screen.findByText(A_FLOW.subject);
    expect(detail).not.toHaveBeenCalled();
    expect(screen.queryByText("the actual message text")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText(A_FLOW.subject));

    await screen.findByText("the actual message text");
    expect(detail).toHaveBeenCalledWith(A_FLOW.id);
  });

  it("ends a conversation from an expanded message row", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({ sessions: [] });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [A_FLOW] });
    vi.spyOn(api, "envelopeDetail").mockResolvedValue({
      item: {
        envelope: {
          id: A_FLOW.id,
          type: A_FLOW.type,
          from: A_FLOW.from,
          to: A_FLOW.to,
          subject: A_FLOW.subject,
          urgency: A_FLOW.urgency,
          expects_reply: A_FLOW.expects_reply,
          body: "body",
          refs: [],
          reply_to: null,
          created_at: A_FLOW.created_at,
          expires_at: A_FLOW.expires_at,
        },
        recipient: A_FLOW.recipient,
        state: A_FLOW.state,
        delivered_at: null,
        acked_at: null,
      },
    });
    const endConversation = vi
      .spyOn(api, "endConversation")
      .mockResolvedValue({ root_id: A_FLOW.id, expired: [A_FLOW] });

    mount();
    await screen.findByText(A_FLOW.subject);
    fireEvent.click(screen.getByText(A_FLOW.subject));
    fireEvent.click(await screen.findByText("End conversation"));
    fireEvent.click(await screen.findByText("Yes, end it"));

    await waitFor(() => expect(endConversation).toHaveBeenCalledWith(A_FLOW.id));
  });

  it("removes an agent from the directory with no secret prompt", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({ sessions: [STALE_SESSION] });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [] });
    const deregister = vi
      .spyOn(api, "deregisterSession")
      .mockResolvedValue({ handle: STALE_SESSION.handle, deregistered: true });

    mount();
    await screen.findByText(STALE_SESSION.handle);
    fireEvent.click(screen.getByText("Remove"));
    fireEvent.click(await screen.findByText("Yes, remove"));

    await waitFor(() => expect(deregister).toHaveBeenCalledWith(STALE_SESSION.handle));
  });

  it("sends as the owner with the composed schema, no handle or secret asked for", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({ sessions: [ACTIVE_SESSION] });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [] });
    vi.spyOn(api, "listVaults").mockResolvedValue([]);
    const sendAsOwner = vi.spyOn(api, "sendAsOwner").mockResolvedValue({
      envelopes: [],
      recipients: [ACTIVE_SESSION.handle],
      broadcast_query: null,
    });

    mount();
    await screen.findByText(ACTIVE_SESSION.handle);
    fireEvent.click(screen.getByText("Send a message"));

    expect(screen.queryByPlaceholderText(/secret/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Agent ID, or *"), {
      target: { value: ACTIVE_SESSION.handle },
    });
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "a note from the owner" },
    });
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "hello there" } });
    fireEvent.click(screen.getByText("Send", { selector: "button" }));

    await waitFor(() =>
      expect(sendAsOwner).toHaveBeenCalledWith(
        expect.objectContaining({
          to: ACTIVE_SESSION.handle,
          subject: "a note from the owner",
          body: "hello there",
        }),
      ),
    );
  });

  it("refuses to send an over-budget message before it ever reaches the hub", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({ sessions: [] });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [] });
    vi.spyOn(api, "listVaults").mockResolvedValue([]);
    const sendAsOwner = vi.spyOn(api, "sendAsOwner");

    mount();
    await screen.findByText(/No agents yet/i);
    fireEvent.click(screen.getByText("Send a message"));

    fireEvent.change(screen.getByPlaceholderText("Agent ID, or *"), {
      target: { value: "*" },
    });
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "s" } });
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "x".repeat(5000) },
    });
    fireEvent.click(screen.getByText("Send", { selector: "button" }));

    await screen.findByText(/over the limit/i);
    expect(sendAsOwner).not.toHaveBeenCalled();
  });
});

/**
 * SPEC-405 deliverable #5: "jargon-free copy (lint, both screens ...)".
 * system.md §3 rule 0 — no protocol name, standard, acronym, transport or
 * implementation word in a label, heading, button, badge, status line or
 * option name. Same scan shape as `Exposure.test.tsx`'s own lint.
 */
describe("Agents screen copy — no jargon in the surface (system.md §3 rule 0)", () => {
  const BANNED = [
    /\bmcp\b/i,
    /\boauth\b/i,
    /\bjwt\b/i,
    /\bttl\b/i,
    /\basgi\b/i,
    /\bapi\b/i,
    /\bjson\b/i,
    /\brfc\s*\d/i,
    /\bbearer\b/i,
    /\benvelope\b/i,
  ];

  it("no heading, button, badge, or field label uses a protocol name or acronym", async () => {
    vi.spyOn(api, "listSessions").mockResolvedValue({
      sessions: [ACTIVE_SESSION, STALE_SESSION],
    });
    vi.spyOn(api, "messageFlows").mockResolvedValue({ flows: [A_FLOW] });

    mount();
    await screen.findByText(ACTIVE_SESSION.handle);

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...Array.from(document.querySelectorAll(".badge, .card__title, .field__label")),
    ];

    expect(controls.length).toBeGreaterThan(5);
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});
