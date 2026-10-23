/**
 * Memories › Needs review (SPEC-208's dashboard mirror, issue 375).
 *
 * The curator files simple captures on its own and *proposes* anything
 * bigger — a merge, a rename, a retirement (SPEC-206, format spec §8). Each
 * proposal waits here, one card each, until the person approves or rejects
 * it — the same calls the review MCP App makes inside a chat
 * (`GET /api/vaults/{key}/review`, `POST …/review/{permalink}/decision`).
 */
import { useEffect, useState } from "react";

import {
  Button,
  Card,
  CardBody,
  CardHeader,
  Disclosure,
  EmptyState,
  ErrorState,
  LoadingState,
  StatusPill,
  useToast,
} from "../components";
import type { ProposalSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { count, exactTime, shortDate } from "../lib/format";
import { ReviewIcon } from "../shell/icons";
import "./memories.css";

interface QueuedProposal {
  vault: string;
  proposal: ProposalSummary;
}

function keyOf(item: QueuedProposal): string {
  return `${item.vault}:${item.proposal.permalink}`;
}

export function ReviewQueue() {
  const toast = useToast();
  const [items, setItems] = useState<QueuedProposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const vaults = await api.listVaults();
        const queues = await Promise.all(
          vaults.map(async (vault) => ({
            vault: vault.key,
            result: await api.listReviewQueue(vault.key),
          })),
        );
        if (cancelled) return;
        setItems(
          queues.flatMap((queue) =>
            queue.result.proposals.map((proposal) => ({ vault: queue.vault, proposal })),
          ),
        );
      } catch (err) {
        if (!cancelled) setError(describeApiError(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  async function decide(item: QueuedProposal, decision: "approved" | "rejected") {
    setBusy(keyOf(item));
    try {
      await api.decideReview(item.vault, item.proposal.permalink, decision);
      setItems((prev) => prev?.filter((other) => keyOf(other) !== keyOf(item)) ?? prev);
      toast.show(
        decision === "approved"
          ? `Approved: ${item.proposal.title}. palaia applies it now.`
          : `Rejected: ${item.proposal.title}. Nothing changes.`,
      );
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setBusy(null);
    }
  }

  if (items === null) {
    if (error) {
      return (
        <ErrorState
          title="Couldn't load what needs review"
          details={error}
          onRetry={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        >
          palaia didn't answer with the curator's proposals.
        </ErrorState>
      );
    }
    return <LoadingState label="Looking for proposals…" />;
  }

  if (items.length === 0) {
    return (
      <EmptyState mark={<ReviewIcon className="icon icon--xl" />} title="Nothing to review">
        palaia asks you here before it merges, renames or archives a note. New notes are filed
        without asking.
      </EmptyState>
    );
  }

  return (
    <div className="stack stack--4">
      <p className="t-muted">
        {count(items.length, "proposal", "proposals")} waiting. Nothing changes until you decide.
      </p>
      {items.map((item) => {
        const id = keyOf(item);
        const created = item.proposal.created;
        return (
          <Card key={id}>
            <CardHeader
              title={item.proposal.title}
              description={
                <span className="review-meta">
                  <span>{item.vault}</span>
                  {created ? (
                    <span title={exactTime(created)}>· proposed {shortDate(created) || created}</span>
                  ) : null}
                </span>
              }
              actions={<StatusPill tone="info">Needs review</StatusPill>}
            />
            <CardBody className="stack stack--3">
              <Disclosure summary="Details">
                <pre className="review-body">
                  {item.proposal.body || "No details were attached to this proposal."}
                </pre>
              </Disclosure>
              <div className="row row--wrap">
                <Button
                  size="sm"
                  disabled={busy !== null}
                  loading={busy === id}
                  onClick={() => void decide(item, "approved")}
                >
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="plain"
                  disabled={busy !== null}
                  onClick={() => void decide(item, "rejected")}
                >
                  Reject
                </Button>
              </div>
            </CardBody>
          </Card>
        );
      })}
    </div>
  );
}
