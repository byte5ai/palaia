import type { Story } from "@ladle/react";
import { MemoryRouter } from "react-router-dom";

import { DownloadIcon } from "../shell/icons";
import { Button, LinkButton } from "./Button";

export default {
  title: "Actions / Button",
};

export const Variants: Story = () => (
  <div className="row row--wrap">
    <Button variant="primary">Download backup</Button>
    <Button>Cancel</Button>
    <Button variant="plain">Show configuration</Button>
    <Button variant="destructive">Revoke access</Button>
    <Button variant="danger">Delete memory</Button>
  </div>
);

export const Sizes: Story = () => (
  <div className="row row--wrap">
    <Button size="sm">Compact (32 px)</Button>
    <Button>Default (40 px)</Button>
    <Button size="lg" variant="primary">
      Onboarding (48 px)
    </Button>
  </div>
);

export const States: Story = () => (
  <div className="row row--wrap">
    <Button variant="primary">
      <DownloadIcon className="icon" />
      Download backup
    </Button>
    <Button variant="primary" loading>
      Preparing the file…
    </Button>
    <Button disabled>Disabled</Button>
  </div>
);

export const AsLink: Story = () => (
  <MemoryRouter>
    <div className="row row--wrap">
      <LinkButton to="/apps" variant="primary">
        Connect an AI app
      </LinkButton>
      <LinkButton to="/settings">Open Settings</LinkButton>
    </div>
  </MemoryRouter>
);
