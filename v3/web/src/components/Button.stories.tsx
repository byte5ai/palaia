import type { Story } from "@ladle/react";

import { Button, type ButtonProps, IconButton } from "./Button";

export default {
  title: "Actions / Button",
};

export const Variants: Story = () => (
  <div className="row row--wrap">
    <Button>Secondary (default)</Button>
    <Button variant="primary">Primary</Button>
    <Button variant="signal">Signal</Button>
    <Button variant="ghost">Ghost</Button>
    <Button variant="quiet">Quiet</Button>
    <Button variant="risk">Risk</Button>
  </div>
);

export const Sizes: Story = () => (
  <div className="row row--wrap">
    <Button size="sm">Small</Button>
    <Button size="md">Medium (default)</Button>
    <Button size="lg">Large</Button>
  </div>
);

export const States: Story = () => (
  <div className="row row--wrap">
    <Button>Default</Button>
    <Button disabled>Disabled</Button>
    <Button shortcut="⌘K">With shortcut</Button>
    <Button variant="primary" shortcut="⏎">
      Primary with shortcut
    </Button>
  </div>
);

export const Block: Story = () => (
  <div style={{ maxWidth: 280 }}>
    <Button variant="quiet" block>
      Full width (quiet)
    </Button>
  </div>
);

export const IconOnly: Story = () => (
  <div className="row">
    <IconButton title="Close">
      <svg className="icon--sm" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 6l12 12M18 6 6 18" />
      </svg>
    </IconButton>
  </div>
);

export const Playground: Story<ButtonProps> = (props) => <Button {...props} />;
Playground.args = { children: "Playground" };
Playground.argTypes = {
  variant: {
    control: { type: "select" },
    options: ["secondary", "primary", "signal", "ghost", "quiet", "risk"],
  },
  size: { control: { type: "select" }, options: ["sm", "md", "lg"] },
  block: { control: { type: "boolean" } },
  disabled: { control: { type: "boolean" } },
};
