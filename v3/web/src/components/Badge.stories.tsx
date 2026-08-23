import type { Story } from "@ladle/react";

import { Badge, Chip, Dot } from "./Badge";

export default {
  title: "Status / Badge",
};

export const Variants: Story = () => (
  <div className="stack stack--2">
    <Badge variant="ok">Healthy</Badge>
    <Badge variant="warn">Needs attention</Badge>
    <Badge variant="risk">Broken</Badge>
    <Badge variant="info">Context</Badge>
    <Badge variant="neutral" dot={false}>
      No dot
    </Badge>
    <Badge variant="ok" live>
      Live (event-stream-backed)
    </Badge>
  </div>
);

export const Dots: Story = () => (
  <div className="row">
    <Dot variant="ok" />
    <Dot variant="warn" />
    <Dot variant="risk" />
    <Dot live />
  </div>
);

export const Chips: Story = () => (
  <div className="row">
    <Chip>session · web</Chip>
    <Chip mono>3f2a91</Chip>
  </div>
);
