import type { Story } from "@ladle/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";

import { Button } from "./Button";
import { LabeledInput } from "./Field";
import { PageHeader } from "./PageHeader";
import { Stepper, StepperPanel, type StepperStep } from "./Stepper";
import { TabLinks } from "./TabLinks";

export default {
  title: "Layout / PageHeader, Tabs, Stepper",
};

export const Headers: Story = () => (
  <MemoryRouter initialEntries={["/memories"]}>
    <div className="stack">
      <PageHeader
        title="Automations"
        description="Let palaia act when something happens in your memories."
        actions={<Button variant="primary">New automation</Button>}
      />
      <PageHeader title="Backups" back={{ to: "/settings", label: "Settings" }} />
      <TabLinks
        label="Memories"
        items={[
          { to: "/memories", label: "Browse", end: true },
          { to: "/memories/review", label: "Needs review", count: 2 },
        ]}
      />
    </div>
  </MemoryRouter>
);

const LABELS = ["Your account", "Where you'll use palaia", "Your first memory", "Connect an AI app", "Done"];

export const Onboarding: Story = () => {
  const [index, setIndex] = useState(2);
  const steps: StepperStep[] = LABELS.map((label, i) => ({
    id: String(i),
    label,
    state: i < index ? "done" : i === index ? "current" : "todo",
  }));
  return (
    <Stepper steps={steps} currentIndex={index} barEnd={<Button variant="plain">Skip setup</Button>}>
      <StepperPanel
        title="Create your first memory"
        description="A memory is a folder of notes your AI apps read and write. You can add more later."
        back={
          <Button onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0}>
            Back
          </Button>
        }
        primary={
          <Button variant="primary" onClick={() => setIndex((i) => Math.min(LABELS.length - 1, i + 1))}>
            Continue
          </Button>
        }
      >
        <LabeledInput label="Name" placeholder="work" hint="Lowercase letters, numbers and dashes." />
        <LabeledInput label="What it's for" optional placeholder="Projects, decisions and notes for my team" />
      </StepperPanel>
    </Stepper>
  );
};
