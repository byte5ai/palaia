import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type {
  TelegramBotStatus,
  TelegramStatus,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import type { EventStreamState } from "../lib/events";
import { useEventStream } from "../lib/events";
import { FakeEventSource } from "../lib/testEventSource";
import { Telegram } from "./Telegram";

const NOW = Date.now() / 1000;

const POLLING_OK: TelegramBotStatus = {
  key: "support",
  label: "Support bot",
  configured_label: "Support bot",
  transport: "polling",
  enabled: true,
  token_secret: "telegram_support",
  webhook_secret: null,
  token_stored: true,
  webhook_secret_stored: null,
  polling: {
    running: true,
    last_ok_at: NOW - 5,
    last_error: null,
    last_error_at: null,
    consecutive_failures: 0,
  },
  last_update_at: NOW - 120,
  last_check: null,
};

const POLLING_FAILING: TelegramBotStatus = {
  ...POLLING_OK,
  key: "broken",
  label: "broken",
  configured_label: null,
  token_secret: "telegram_broken",
  polling: {
    running: true,
    last_ok_at: NOW - 600,
    last_error: "telegram getUpdates failed (HTTP 401): Unauthorized",
    last_error_at: NOW - 30,
    consecutive_failures: 3,
  },
  last_update_at: null,
};

const WEBHOOK_UNCHECKED: TelegramBotStatus = {
  key: "hooked",
  label: "hooked",
  configured_label: null,
  transport: "webhook",
  enabled: true,
  token_secret: "telegram_hooked",
  webhook_secret: "telegram_hooked_webhook",
  token_stored: true,
  webhook_secret_stored: true,
  polling: null,
  last_update_at: null,
  last_check: null,
};

const DISABLED: TelegramBotStatus = {
  ...WEBHOOK_UNCHECKED,
  key: "asleep",
  label: "asleep",
  transport: "polling",
  enabled: false,
  token_secret: "telegram_asleep",
  webhook_secret: null,
  webhook_secret_stored: null,
};

const NO_TOKEN: TelegramBotStatus = {
  ...WEBHOOK_UNCHECKED,
  key: "fresh",
  label: "fresh",
  transport: "polling",
  token_secret: "telegram_fresh",
  webhook_secret: null,
  token_stored: false,
  webhook_secret_stored: null,
};

const FULL_STATUS: TelegramStatus = {
  bots: [POLLING_OK, POLLING_FAILING, WEBHOOK_UNCHECKED, DISABLED, NO_TOKEN],
  routes: [
    {
      bot: "support",
      chat: "-1001",
      kind: "messenger",
      destination: "messenger:ops-agent",
      target: {
        kind: "messenger",
        to: "ops-agent",
        message_type: "inform",
        urgency: "normal",
      },
    },
    {
      bot: "support",
      chat: "*",
      kind: "inbox",
      destination: "inbox:work",
      target: { kind: "inbox", vault: "work" },
    },
    {
      bot: "hooked",
      chat: "@opsroom",
      kind: "event",
      destination: "event",
      target: { kind: "event" },
    },
  ],
  grants: [{ profile: "desk", bots: ["support"], chats: ["*"] }],
  vaults: ["work"],
  messenger: true,
  warnings: [],
  editable: true,
  recent: [
    {
      at: NOW - 10,
      bot: "support",
      chat_id: -1003,
      chat_type: "supergroup",
      chat_username: "opsroom",
      message_id: 3,
      text_chars: 12,
      routed: false,
      destination: null,
      delivered: false,
      detail: "no route claims support/-1003.",
      candidates: ["-1003", "@opsroom", "*"],
    },
    {
      at: NOW - 20,
      bot: "support",
      chat_id: -1002,
      chat_type: "supergroup",
      chat_username: null,
      message_id: 2,
      text_chars: 40,
      routed: true,
      destination: "inbox:work",
      delivered: false,
      detail:
        "delivery to inbox:work failed (RuntimeError); the hub log has the details",
      candidates: null,
    },
    {
      at: NOW - 30,
      bot: "support",
      chat_id: -1001,
      chat_type: "supergroup",
      chat_username: null,
      message_id: 1,
      text_chars: 5,
      routed: true,
      destination: "messenger:ops-agent",
      delivered: true,
      detail: "relayed to messenger recipient 'ops-agent' as the owner",
      candidates: null,
    },
  ],
};

const EMPTY_STATUS: TelegramStatus = {
  bots: [],
  routes: [],
  grants: [],
  recent: [],
  vaults: ["work"],
  messenger: true,
  warnings: [],
  editable: true,
};

/** A stream literal written before `telegramActivityCount` existed — the
 * field is optional precisely so this still type-checks. */
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
        children: [{ index: true, element: <Telegram /> }],
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

/** The real `useEventStream` over a `FakeEventSource`, so a test fires a
 * genuine SSE frame — the same harness Agents.test.tsx uses. */
function LiveShell() {
  const stream = useEventStream(
    FakeEventSource as unknown as typeof EventSource,
  );
  return <Outlet context={stream} />;
}

function mountLive() {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <LiveShell />,
        children: [{ index: true, element: <Telegram /> }],
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

describe("Telegram screen", () => {
  it("renders every bot's state, the routing table and recent messages", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(FULL_STATUS);

    mount();

    await screen.findByText("Connected");
    // One badge per state the hub can report.
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Failing")).toBeInTheDocument();
    expect(screen.getByText("Not checked yet")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText("Token missing")).toBeInTheDocument();
    // The failing bot's error, as a sub-line.
    expect(
      screen.getByText("telegram getUpdates failed (HTTP 401): Unauthorized"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Last message received/)).toBeInTheDocument();
    // A switched-off bot has nothing to check.
    expect(screen.getAllByText("Check connection")).toHaveLength(4);

    // Where messages go, in plain words.
    expect(screen.getByText("every chat")).toBeInTheDocument();
    expect(screen.getAllByText("Messenger → ops-agent")).toHaveLength(2);
    expect(screen.getAllByText("Inbox of vault work")).toHaveLength(1);
    expect(screen.getByText("Hub event")).toBeInTheDocument();

    // Recent messages: one of each outcome, newest first.
    expect(screen.getByText(/No rule matched/)).toBeInTheDocument();
    for (const key of ["-1003", "@opsroom", "*"]) {
      expect(
        screen.getByText(key, { selector: ".chip" }),
      ).toBeInTheDocument();
    }
    expect(
      screen.getByText(/Not delivered — delivery to inbox:work failed/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Delivered to/)).toBeInTheDocument();
    const outcomes = Array.from(document.querySelectorAll("p.t-sm")).map(
      (node) => node.textContent ?? "",
    );
    const order = ["No rule matched", "Not delivered", "Delivered to"].map(
      (word) => outcomes.findIndex((text) => text.includes(word)),
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it("offers to add the first bot on a hub with none", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(EMPTY_STATUS);

    mount();

    await screen.findByText("No bots yet.");
    expect(screen.getByText(/@BotFather/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a bot" })).toBeInTheDocument();
    const guide = screen.getByRole("link", { name: "setup guide" });
    expect(guide).toHaveAttribute(
      "href",
      expect.stringContaining("v3/docs/telegram.md"),
    );
  });

  it("shows what the running hub cannot serve", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...EMPTY_STATUS,
      warnings: ["telegram route support/* delivers into the inbox of vault 'later'"],
    });

    mount();

    await screen.findByText(/inbox of vault 'later'/);
    expect(document.querySelector(".banner--warn")).not.toBeNull();
  });

  it("shows a hub error in a banner, not a crash", async () => {
    vi.spyOn(api, "telegramStatus").mockRejectedValue(
      new ApiError("/api/telegram/status", 500, {
        detail: "the hub is having a bad day",
      }),
    );

    mount();

    await screen.findByText("the hub is having a bad day");
    expect(document.querySelector(".banner--warn")).not.toBeNull();
  });

  it("checks a bot's connection on demand and shows what Telegram said", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [WEBHOOK_UNCHECKED],
    });
    const check = vi.spyOn(api, "checkTelegramBot").mockResolvedValue({
      ...WEBHOOK_UNCHECKED,
      last_check: {
        ok: true,
        username: "fake_bot",
        checked_at: Date.now() / 1000,
        error: null,
      },
    });

    mount();
    await screen.findByText("Not checked yet");
    fireEvent.click(screen.getByText("Check connection"));

    await waitFor(() => expect(check).toHaveBeenCalledWith("hooked"));
    await screen.findByText(/Telegram knows it as @fake_bot/);
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("shows a refused check as a failing bot with the reason", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [WEBHOOK_UNCHECKED],
    });
    vi.spyOn(api, "checkTelegramBot").mockResolvedValue({
      ...WEBHOOK_UNCHECKED,
      last_check: {
        ok: false,
        username: null,
        checked_at: Date.now() / 1000,
        error: "telegram getMe failed (HTTP 401): Unauthorized",
      },
    });

    mount();
    await screen.findByText("Not checked yet");
    fireEvent.click(screen.getByText("Check connection"));

    await screen.findByText("telegram getMe failed (HTTP 401): Unauthorized");
    expect(screen.getByText("Failing")).toBeInTheDocument();
  });
});

describe("editing (issue 463)", () => {
  it("adds a bot and stores its token in the secret store, by name", async () => {
    vi.spyOn(api, "telegramStatus")
      .mockResolvedValueOnce(EMPTY_STATUS)
      .mockResolvedValue({ ...EMPTY_STATUS, bots: [POLLING_OK] });
    const create = vi.spyOn(api, "createTelegramBot").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [{ ...POLLING_OK, token_stored: false }],
    });
    const store = vi
      .spyOn(api, "storeSecret")
      .mockResolvedValue({ name: "telegram_support", created_at: 1, updated_at: 1 });

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add a bot" }));
    fireEvent.change(screen.getByLabelText("Name on the hub"), {
      target: { value: "support" },
    });
    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "Support bot" },
    });
    fireEvent.change(screen.getByLabelText("Bot token"), {
      target: { value: "123:secret-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add bot" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        key: "support",
        label: "Support bot",
        transport: "polling",
        enabled: true,
      }),
    );
    // The token went to the secret store under the bot's secret name —
    // and never in the bot's own request.
    await waitFor(() =>
      expect(store).toHaveBeenCalledWith("telegram_support", "123:secret-token"),
    );
    expect(JSON.stringify(create.mock.calls)).not.toContain("secret-token");
    await screen.findByText("Connected");
  });

  it("refuses a bot name that is already taken, before asking the hub", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [POLLING_OK],
    });
    const create = vi.spyOn(api, "createTelegramBot");

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add a bot" }));
    fireEvent.change(screen.getByLabelText("Name on the hub"), {
      target: { value: "support" },
    });

    expect(screen.getByText(/already exists/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add bot" })).toBeDisabled();
    expect(create).not.toHaveBeenCalled();
  });

  it("switches a bot off from its editor", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [POLLING_OK],
    });
    const update = vi.spyOn(api, "updateTelegramBot").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [{ ...POLLING_OK, enabled: false, polling: null }],
    });

    mount();
    await screen.findByText("Connected");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const row = screen.getByText("Switched on").closest("label")!;
    fireEvent.click(row.querySelector('[role="switch"]')!);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        "support",
        expect.objectContaining({ enabled: false, label: "Support bot" }),
      ),
    );
    await screen.findByText("Disabled");
  });

  it("says why a bot in use cannot be removed", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...EMPTY_STATUS,
      bots: [POLLING_OK],
    });
    vi.spyOn(api, "deleteTelegramBot").mockRejectedValue(
      new ApiError("/api/telegram/bots/support", 409, {
        detail: "Telegram bot 'support' is still used by rule(s) support/-1001.",
      }),
    );

    mount();
    await screen.findByText("Connected");
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove the bot" }));

    await screen.findByText(/still used by rule\(s\) support\/-1001/);
  });

  it("writes a rule straight from a message no rule matched", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...FULL_STATUS,
      routes: [],
    });
    const create = vi.spyOn(api, "createTelegramRoute").mockResolvedValue({
      ...FULL_STATUS,
    });

    mount();
    await screen.findByText(/No rule matched/);
    fireEvent.click(screen.getByRole("button", { name: "@opsroom" }));

    // Prefilled with the bot and the chat key picked.
    expect(screen.getByLabelText("Chat")).toHaveValue("@opsroom");
    expect(screen.getByLabelText("Bot")).toHaveValue("support");
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        bot: "support",
        chat: "@opsroom",
        destination: { kind: "inbox", vault: "work" },
      }),
    );
  });

  it("edits a rule in place, addressed by its old bot and chat", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(FULL_STATUS);
    const replace = vi
      .spyOn(api, "replaceTelegramRoute")
      .mockResolvedValue(FULL_STATUS);

    mount();
    await screen.findByText("Hub event");
    const row = screen.getByText("Hub event").closest("tr")!;
    fireEvent.click(row.querySelector("button")!);
    fireEvent.click(screen.getByRole("radio", { name: "An agent's inbox" }));
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "ops-agent" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("hooked", "@opsroom", {
        bot: "hooked",
        chat: "@opsroom",
        destination: {
          kind: "messenger",
          to: "ops-agent",
          message_type: "inform",
          urgency: "normal",
        },
      }),
    );
  });

  it("shows a refused rule's reason from the hub", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(FULL_STATUS);
    vi.spyOn(api, "createTelegramRoute").mockRejectedValue(
      new ApiError("/api/telegram/routes", 422, {
        detail: [{ msg: "Value error, 'x' is not a usable chat reference." }],
      }),
    );

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add a rule" }));
    fireEvent.change(screen.getByLabelText("Chat"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    await screen.findByText("'x' is not a usable chat reference.");
  });

  it("lets a tool profile send, offering only profiles without an entry", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(FULL_STATUS);
    const profile = {
      label: null,
      vaults: ["work"],
      stash: false,
      hidden_tools: [],
      semantic_routing: false,
      tool_count: 5,
      upstreams: [],
    };
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([
      { ...profile, path: "desk", telegram: true, managed: false },
      { ...profile, path: "phone", telegram: false, managed: false },
      { ...profile, path: "curator", telegram: false, managed: true },
    ]);
    const put = vi.spyOn(api, "putTelegramGrant").mockResolvedValue(FULL_STATUS);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Let a profile send" }));
    const select = await screen.findByLabelText("Tool profile");
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["phone"]);
    // The profile has no Telegram tools yet — the form says so.
    expect(screen.getByText(/does not carry the Telegram tools yet/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("To these chats"), {
      target: { value: "-1001, @opsroom" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("phone", {
        bots: ["*"],
        chats: ["-1001", "@opsroom"],
      }),
    );
  });

  it("lists who may send, in plain words", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(FULL_STATUS);

    mount();
    await screen.findByText("desk");
    expect(
      screen.getByText("Through Support bot, to every chat"),
    ).toBeInTheDocument();
  });

  it("shows no editing controls when the hub cannot save", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue({
      ...FULL_STATUS,
      editable: false,
    });

    mount();
    await screen.findByText("Connected");
    for (const name of ["Add a bot", "Add a rule", "Let a profile send", "Edit", "Remove"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    // Candidates stay plain chips.
    expect(screen.getByText("-1003", { selector: ".chip" })).toBeInTheDocument();
  });
});

describe("live updates", () => {
  it("turns a burst of telegram events into one refetch (SSE fixture)", async () => {
    const status = vi
      .spyOn(api, "telegramStatus")
      .mockResolvedValue(EMPTY_STATUS);

    mountLive();
    await screen.findByText("No bots yet.");
    expect(status).toHaveBeenCalledTimes(1);

    const source = FakeEventSource.instances.at(-1)!;
    for (const messageId of [1, 2, 3]) {
      act(() => {
        source.emit("telegram.message.received", {
          event: "telegram.message.received",
          data: { bot: "support", message_id: messageId },
        });
      });
    }

    await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(status).toHaveBeenCalledTimes(2);
  });

  it("refetches once a slow delivery's outcome is recorded", async () => {
    // `received` fires before the delivery starts; `handled` after the hub
    // recorded the outcome — the one a slow delivery depends on.
    const status = vi
      .spyOn(api, "telegramStatus")
      .mockResolvedValueOnce(EMPTY_STATUS)
      .mockResolvedValueOnce({
        ...EMPTY_STATUS,
        recent: [FULL_STATUS.recent[2]],
      });

    mountLive();
    await screen.findByText("No messages yet.");

    const source = FakeEventSource.instances.at(-1)!;
    act(() => {
      source.emit("telegram.message.handled", {
        event: "telegram.message.handled",
        data: { bot: "support", message_id: 1, delivered: true },
      });
    });

    await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
    await screen.findByText(/Delivered to/);
  });

  it("refetches when a bot starts failing", async () => {
    const status = vi
      .spyOn(api, "telegramStatus")
      .mockResolvedValueOnce({ ...EMPTY_STATUS, bots: [POLLING_OK] })
      .mockResolvedValueOnce({ ...EMPTY_STATUS, bots: [POLLING_FAILING] });

    mountLive();
    await screen.findByText("Connected");

    const source = FakeEventSource.instances.at(-1)!;
    act(() => {
      source.emit("telegram.bot.state", {
        event: "telegram.bot.state",
        data: { bot: "broken", state: "failing", detail: "HTTP 401" },
      });
    });

    await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
    await screen.findByText("Failing");
  });
});

/**
 * system.md §3 rule 0 — no protocol name, transport or implementation word
 * in a heading, button, badge or field label. Agents.test.tsx's list, plus
 * this screen's own risk: the two ways a bot can receive ("webhook", "long
 * polling") belong in `title` attributes and sub-lines only. "token" is
 * not banned — system.md lists it among the words palaia teaches and
 * keeps, and "Token missing" is the badge that names the day-one fix.
 */
describe("Telegram screen copy — no jargon in the surface (system.md §3 rule 0)", () => {
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
    /\bwebhook\b/i,
    /\bpolling\b/i,
    /\blong[\s-]?poll/i,
    /\bgetme\b/i,
  ];

  it("no heading, button, badge, or field label uses a protocol name or acronym", async () => {
    vi.spyOn(api, "telegramStatus").mockResolvedValue(FULL_STATUS);

    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    mount();
    await screen.findByText("Connected");
    // Open every editor, so their labels and buttons are checked too.
    fireEvent.click(screen.getByRole("button", { name: "Add a bot" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a rule" }));
    fireEvent.click(screen.getByRole("button", { name: "Let a profile send" }));
    await screen.findByText(/Every tool profile already has an entry/);

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...Array.from(
        document.querySelectorAll(
          ".badge, .card__title, .field__label, .segmented__item, .switchrow",
        ),
      ),
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
