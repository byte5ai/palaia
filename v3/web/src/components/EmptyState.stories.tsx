import type { Story } from "@ladle/react";

import { Button } from "./Button";
import { DoneState, EmptyState } from "./EmptyState";

function InboxGlyph() {
  return (
    <svg className="icon--lg" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 13.5h4l1.2 2.5h5.6l1.2-2.5h4" />
      <path d="M4 13.5 6.7 5h10.6L20 13.5V20H4z" />
    </svg>
  );
}

function DoneGlyph() {
  return (
    <svg className="donemark" viewBox="0 0 48 48" aria-hidden="true">
      <circle cx="24" cy="24" r="20" />
      <path d="M15.5 24.6 21.5 31.2 33.2 17.4" />
    </svg>
  );
}

export default {
  title: "Empty & first-run / EmptyState",
};

export const FirstRun: Story = () => (
  <EmptyState
    mark={<InboxGlyph />}
    title="Nothing captured yet."
    actions={<Button variant="primary">Connect a client</Button>}
  >
    Connect a client and ask it to remember something — captures land here first.
  </EmptyState>
);

export const Done: Story = () => (
  <DoneState
    mark={<DoneGlyph />}
    title="The queue is clear."
    recapLabel="since monday"
    recap={
      <ul className="factline">
        <li>
          <span className="fact-dot" />
          <span className="t-mono">128</span> added without asking
        </li>
        <li>
          <span className="fact-dot" />
          <span className="t-mono">9</span> approved, <span className="t-mono">2</span> rejected
        </li>
      </ul>
    }
  >
    A clear queue is the normal state, not a lucky day.
  </DoneState>
);
