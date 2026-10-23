import type { Story } from "@ladle/react";

import { Chip, Dot } from "./Badge";
import { StatusPill } from "./StatusPill";

export default {
  title: "Status / StatusPill",
};

export const Tones: Story = () => (
  <div className="row row--wrap">
    <StatusPill tone="ok">Connected</StatusPill>
    <StatusPill tone="info">Waiting for first use</StatusPill>
    <StatusPill tone="warn">Needs Cloud mode</StatusPill>
    <StatusPill tone="error">Can't reach</StatusPill>
    <StatusPill tone="neutral">Not set up</StatusPill>
  </div>
);

export const DotsAndChips: Story = () => (
  <div className="stack stack--3">
    <div className="row">
      <Dot variant="ok" />
      <span>Running · Private</span>
    </div>
    <div className="row">
      <Dot variant="risk" />
      <span>Can't reach palaia</span>
    </div>
    <div className="row">
      <Chip>work</Chip>
      <Chip mono>projects/website</Chip>
    </div>
  </div>
);
