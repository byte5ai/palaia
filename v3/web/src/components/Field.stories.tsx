import type { Story } from "@ladle/react";
import { useState } from "react";

import { LabeledInput, Segmented, SwitchRow } from "./Field";

export default {
  title: "Forms / Field",
};

export const Inputs: Story = () => (
  <div className="stack" style={{ maxWidth: 320 }}>
    <LabeledInput label="Vault name" placeholder="personal" hint="Agents read this to pick the right memory." />
    <LabeledInput label="Vault path" readOnly value="~/palaia/personal" />
    <LabeledInput label="Endpoint" invalid value="not a url" error="Enter a full https:// URL." />
  </div>
);

export const Switch: Story = () => {
  const [checked, setChecked] = useState(true);
  return (
    <div style={{ maxWidth: 320 }}>
      <SwitchRow
        label="Git"
        consequence="This is your undo — every write becomes a commit."
        checked={checked}
        onChange={setChecked}
      />
    </div>
  );
};

export const SegmentedControl: Story = () => {
  const [value, setValue] = useState<"coding" | "general">("coding");
  return (
    <Segmented
      value={value}
      onChange={setValue}
      options={[
        { value: "coding", label: "Coding" },
        { value: "general", label: "General" },
      ]}
    />
  );
};
