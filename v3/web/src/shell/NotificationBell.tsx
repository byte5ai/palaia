/**
 * SPEC-307 deliverable #1's dashboard notification center: a small bell in
 * the shell, backed by `/api/notifications`. No email/push in v1 — the
 * bell itself is the whole surface, so it polls for a fresh unread count
 * rather than needing a dedicated live-push wire.
 */
import { useEffect, useRef, useState } from "react";

import { Button, Card, CardBody, CardHead, EmptyState } from "../components";
import type { NotificationRecord } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { BellIcon } from "./icons";

const POLL_INTERVAL_MS = 20_000;

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell() {
  const [available, setAvailable] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<NotificationRecord[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

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
    function onClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  function toggleOpen() {
    const next = !open;
    setOpen(next);
    if (next) {
      api
        .listNotifications()
        .then(setEntries)
        .catch(() => setEntries([]));
    }
  }

  async function markRead(id: number) {
    await api.markNotificationRead(id);
    setEntries(
      (prev) =>
        prev?.map((n) => (n.id === id ? { ...n, read: true } : n)) ?? prev,
    );
    refreshUnreadCount();
  }

  async function markAllRead() {
    await api.markAllNotificationsRead();
    setEntries((prev) => prev?.map((n) => ({ ...n, read: true })) ?? prev);
    setUnreadCount(0);
  }

  if (!available) return null;

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="cmdk"
        style={{ width: 36, justifyContent: "center", position: "relative" }}
        onClick={toggleOpen}
        aria-label={
          unreadCount > 0
            ? `${unreadCount} unread notifications`
            : "Notifications"
        }
      >
        <BellIcon className="icon--sm" />
        {unreadCount > 0 ? (
          <span
            className="dot dot--live"
            style={{
              position: "absolute",
              top: 4,
              right: 4,
              width: 6,
              height: 6,
            }}
          />
        ) : null}
      </button>
      {open ? (
        <Card
          variant="raised"
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 8px)",
            width: 340,
            zIndex: 20,
          }}
        >
          <CardHead title="notifications">
            {entries && entries.some((n) => !n.read) ? (
              <Button variant="quiet" size="sm" onClick={markAllRead}>
                Mark all read
              </Button>
            ) : null}
          </CardHead>
          <CardBody
            className="stack stack--2"
            style={{ maxHeight: 360, overflowY: "auto" }}
          >
            {entries === null ? (
              <p className="t-sm t-subtle">Loading…</p>
            ) : entries.length === 0 ? (
              <EmptyState
                mark={<BellIcon className="icon--lg" />}
                title="Nothing here yet."
              >
                An automation with a notify action will show up here.
              </EmptyState>
            ) : (
              entries.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className="listrow"
                  style={{
                    width: "100%",
                    textAlign: "left",
                    opacity: entry.read ? 0.6 : 1,
                  }}
                  onClick={() => markRead(entry.id)}
                >
                  <div className="stack stack--1">
                    <span className="t-sm">{entry.title}</span>
                    {entry.body ? (
                      <span className="t-xs t-subtle">{entry.body}</span>
                    ) : null}
                    <span className="t-xs t-subtle" title={entry.created_at}>
                      {relativeTime(entry.created_at)}
                    </span>
                  </div>
                </button>
              ))
            )}
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}
