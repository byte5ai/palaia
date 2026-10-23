import type { Story } from "@ladle/react";

import { VaultsIcon } from "../shell/icons";
import { Button } from "./Button";
import { Card, CardHeader } from "./Card";
import { EmptyState, ErrorState, InlineEmpty, LoadingState } from "./EmptyState";

export default {
  title: "Feedback / Empty, loading, error",
};

export const EmptyPage: Story = () => (
  <EmptyState
    mark={<VaultsIcon className="icon icon--xl" />}
    title="No memories yet"
    actions={<Button variant="primary">Create memory</Button>}
  >
    Create one to start saving notes.
  </EmptyState>
);

export const EmptySection: Story = () => (
  <Card style={{ maxWidth: 560 }}>
    <CardHeader title="Activity" />
    <InlineEmpty>No activity yet. New and changed notes appear here.</InlineEmpty>
  </Card>
);

export const Loading: Story = () => (
  <div style={{ maxWidth: 560 }}>
    <LoadingState label="Loading your memories…" />
  </div>
);

export const CouldNotLoad: Story = () => (
  <div style={{ maxWidth: 560 }}>
    <ErrorState
      title="Couldn't load your memories"
      details="GET /api/vaults responded 500"
      onRetry={() => {}}
    >
      palaia answered with an error.
    </ErrorState>
  </div>
);
