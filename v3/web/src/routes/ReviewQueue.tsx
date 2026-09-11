/**
 * The review queue (SPEC-208's dashboard mirror, issue 375).
 *
 * The curator files simple captures on its own and *proposes* anything
 * bigger — a merge, a rename, a retirement (SPEC-206, format spec §8).
 * Those proposals waited behind a nav item that led to "not built yet",
 * although the hub already served them (`GET /api/vaults/{key}/review`)
 * and took the decision (`POST …/review/{permalink}/decision`) — the same
 * calls the review-queue MCP App makes inside a chat client. This screen
 * is the admin surface for the same thing: every vault's pending
 * proposals, approve or reject.
 */
import { useEffect, useState } from "react";

import { Badge, Button, Card, CardBody, CardHead, EmptyState, useToast } from "../components";
import { Waiting } from "../components/Skeleton";
import type { ProposalSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { describeApiError } from "../lib/errors";
import { ReviewIcon } from "../shell/icons";

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
  const [open, setOpen] = useState<string | null>(null);

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
      toast.show(decision === "approved" ? "Approved." : "Rejected.");
    } catch (err) {
      toast.show(describeApiError(err));
    } finally {
      setBusy(null);
    }
  }

  if (items === null) {
    return (
      <Card>
        <CardBody className="stack stack--2">
          {error ? (
            <>
              <p className="t-sm t-muted">Could not load the review queue: {error}</p>
              <div className="row">
                <Button
                  size="sm"
                  onClick={() => {
                    setError(null);
                    setAttempt((n) => n + 1);
                  }}
                >
                  Try again
                </Button>
              </div>
            </>
          ) : (
            <Waiting>Looking for proposals…</Waiting>
          )}
        </CardBody>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <Card>
        <CardBody>
          <EmptyState mark={<ReviewIcon className="icon--lg" />} title="Nothing waiting for you.">
            When the curator wants to merge, rename or retire a note, the proposal shows up
            here for you to approve or reject. Simple additions are filed without asking.
          </EmptyState>
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="stack stack--3">
      <p className="t-sm t-muted">
        {items.length} proposal{items.length === 1 ? "" : "s"} waiting. Nothing here happens
        until you decide — approving lets the curator apply it, rejecting drops it.
      </p>
      {items.map((item) => {
        const id = keyOf(item);
        return (
          <Card key={id}>
            <CardHead
              title={item.proposal.title}
              meta={<Badge variant="neutral">{item.vault}</Badge>}
            />
            <CardBody className="stack stack--2">
              <div className="row row--wrap" style={{ gap: 8 }}>
                <span className="chip chip--mono">{item.proposal.permalink}</span>
                {item.proposal.created ? (
                  <span className="t-xs t-subtle">proposed {item.proposal.created}</span>
                ) : null}
              </div>
              <Button
                size="sm"
                variant="quiet"
                onClick={() => setOpen((current) => (current === id ? null : id))}
              >
                {open === id ? "Hide details" : "Show details"}
              </Button>
              {open === id ? (
                <pre className="snippet snippet--block" style={{ whiteSpace: "pre-wrap" }}>
                  {item.proposal.body || "(no details attached)"}
                </pre>
              ) : null}
              <div className="row" style={{ gap: 8 }}>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => void decide(item, "approved")}
                >
                  Approve
                </Button>
                <Button
                  size="sm"
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
