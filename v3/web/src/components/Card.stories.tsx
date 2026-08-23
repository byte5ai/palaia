import type { Story } from "@ladle/react";

import { Button } from "./Button";
import { Card, CardBody, CardFoot, CardHead, CardSubject } from "./Card";

export default {
  title: "Surfaces / Card",
};

export const ContainerLabel: Story = () => (
  <Card style={{ maxWidth: 420 }}>
    <CardHead title="activity" meta="14 d" />
    <CardBody>
      <p className="t-sm t-muted">A container's own head is a quiet, lowercase label.</p>
    </CardBody>
    <CardFoot>
      <Button size="sm">Reindex now</Button>
    </CardFoot>
  </Card>
);

export const SubjectHeading: Story = () => (
  <Card style={{ maxWidth: 420 }}>
    <CardHead meta="3f2a">
      <CardSubject>Claude Code CLI</CardSubject>
    </CardHead>
    <CardBody>
      <p className="t-sm t-muted">
        A head that names a subject gets a real heading — 15px/600, ink, sans.
      </p>
    </CardBody>
  </Card>
);

export const Elevation: Story = () => (
  <div className="row row--wrap" style={{ alignItems: "flex-start" }}>
    <Card variant="flat" style={{ width: 200, padding: 16 }}>
      flat
    </Card>
    <Card style={{ width: 200, padding: 16 }}>default (raised shadow)</Card>
    <Card variant="raised" style={{ width: 200, padding: 16 }}>
      raised (popover shadow)
    </Card>
  </div>
);
