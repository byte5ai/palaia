import type { Story } from "@ladle/react";
import { useState } from "react";

import { Field, LabeledInput, Segmented, Switch } from "./Field";

export default {
  title: "Forms / Field",
};

export const RequiredAndOptional: Story = () => (
  <div className="stack" style={{ maxWidth: 420 }}>
    <LabeledInput label="Name" placeholder="work" hint="Lowercase letters, numbers and dashes, e.g. work." />
    <LabeledInput
      label="What it's for"
      optional
      placeholder="Projects, decisions and notes for my team"
      hint="AI apps use this to choose the right memory."
    />
    <Field label="Folder" optional hint="Leave empty to use palaia's data folder.">
      <input className="input input--mono" placeholder="/data/memories/work" />
    </Field>
  </div>
);

export const States: Story = () => (
  <div className="stack" style={{ maxWidth: 420 }}>
    <LabeledInput label="Address" readOnly value="https://palaia.example.com/mcp/default/" />
    <LabeledInput
      label="Public address"
      invalid
      value="palaia.example"
      error="Enter the full address, starting with https://."
    />
  </div>
);

export const Controls: Story = () => {
  const [on, setOn] = useState(true);
  const [theme, setTheme] = useState<"system" | "light" | "dark">("system");
  return (
    <div className="stack" style={{ maxWidth: 420 }}>
      <div className="row">
        <span id="story-switch">Require sign-in for this dashboard</span>
        <Switch checked={on} onChange={setOn} labelledBy="story-switch" />
      </div>
      <label className="checkrow">
        <input type="checkbox" defaultChecked />
        <span>Read</span>
      </label>
      <label className="checkrow">
        <input type="checkbox" />
        <span>Save</span>
      </label>
      <Segmented
        ariaLabel="Appearance"
        value={theme}
        onChange={setTheme}
        options={[
          { value: "system", label: "System" },
          { value: "light", label: "Light" },
          { value: "dark", label: "Dark" },
        ]}
      />
    </div>
  );
};
