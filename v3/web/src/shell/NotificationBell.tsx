/**
 * SPEC-307's notification center: a 36 px bell with an unread count, backed
 * by `/api/notifications`. It polls for the count; the list loads when the
 * panel opens. The panel is positioned against the viewport, so it is never
 * clipped by the sidebar it sits in.
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "../components/Button";
import { InlineEmpty } from "../components/EmptyState";
import type { NotificationRecord } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { BellIcon } from "./icons";

const POLL_INTERVAL_MS = 20_000;
const PANEL_GAP = 8;
const EDGE = 16;
const PANEL_WIDTH = 360;

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function NotificationBell() {
  const [available, setAvailable] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<NotificationRecord[] | null>(null);
  const [position, setPosition] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  function refreshUnreadCount() {
    api
      .unreadNotificationCount()
      .then((result) => {
        setUnreadCount(result.count);
        setAvailable(true);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setAvailable(false);
      });
  }

  useEffect(() => {
    refreshUnreadCount();
    const interval = window.setInterval(refreshUnreadCount, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function toggleOpen() {
    const next = !open;
    if (next && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      const width = Math.min(PANEL_WIDTH, window.innerWidth - 2 * EDGE);
      const left = Math.max(EDGE, Math.min(rect.left, window.innerWidth - width - EDGE));
      setPosition({ top: rect.bottom + PANEL_GAP, left });
    }
    setOpen(next);
    if (next) {
      api
        .listNotifications()
        .then(setEntries)
        .catch(() => setEntries([]));
    }
  }

  // Issue 376: a refused write (a rotated sign-in cookie, a hub that went
  // away) used to be an unhandled rejection — the click did nothing.
  const [actionError, setActionError] = useState<string | null>(null);

  async function markRead(id: number) {
    setActionError(null);
    try {
      await api.markNotificationRead(id);
    } catch (err) {
      setActionError(describeApiError(err));
      return;
    }
    setEntries((prev) => prev?.map((n) => (n.id === id ? { ...n, read: true } : n)) ?? prev);
    refreshUnreadCount();
  }

  async function markAllRead() {
    setActionError(null);
    try {
      await api.markAllNotificationsRead();
    } catch (err) {
      setActionError(describeApiError(err));
      return;
    }
    setEntries((prev) => prev?.map((n) => ({ ...n, read: true })) ?? prev);
    setUnreadCount(0);
  }

  if (!available) return null;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="iconbtn"
        onClick={toggleOpen}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Notifications"
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
      >
        <BellIcon className="icon" />
        {unreadCount > 0 ? (
          <span className="iconbtn__badge" aria-hidden="true">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        ) : null}
      </button>
      {open
        ? createPortal(
            <div
              ref={panelRef}
              className="popover"
              role="dialog"
              aria-label="Notifications"
              style={{ top: position.top, left: position.left }}
            >
              <div className="popover__head">
                <span className="popover__title">Notifications</span>
                {entries && entries.some((n) => !n.read) ? (
                  <Button variant="plain" size="sm" onClick={markAllRead}>
                    Mark all as read
                  </Button>
                ) : null}
              </div>
              <div className="popover__body">
                {actionError ? (
                  <p className="field__error" style={{ padding: "var(--space-3) var(--space-4)" }}>
                    {actionError}
                  </p>
                ) : null}
                {entries === null ? (
                  <InlineEmpty>Loading…</InlineEmpty>
                ) : entries.length === 0 ? (
                  <InlineEmpty>No notifications. Automations can send them here.</InlineEmpty>
                ) : (
                  entries.map((entry) => (
                    <button
                      key={entry.id}
                      type="button"
                      className="listrow"
                      onClick={() => markRead(entry.id)}
                      title={entry.read ? undefined : "Mark as read"}
                    >
                      {entry.read ? null : <span className="dot dot--info" aria-label="Unread" />}
                      <span className="listrow__main">
                        <span className="listrow__title">{entry.title}</span>
                        {entry.body ? <span className="listrow__desc">{entry.body}</span> : null}
                        <span className="listrow__meta" title={entry.created_at}>
                          {relativeTime(entry.created_at)}
                        </span>
                      </span>
                    </button>
                  ))
                )}
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
