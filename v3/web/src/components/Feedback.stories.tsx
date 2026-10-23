import type { Story } from "@ladle/react";
import { useState } from "react";

import { Button } from "./Button";
import { Callout } from "./Callout";
import { ConfirmDialog, Dialog } from "./Dialog";
import { Disclosure } from "./Disclosure";
import { LabeledInput } from "./Field";

export default {
  title: "Feedback / Callout, Disclosure, Dialog",
};

export const Callouts: Story = () => (
  <div className="stack stack--3" style={{ maxWidth: 640 }}>
    <Callout
      tone="warn"
      title="Backups need dashboard sign-in"
      actions={<Button variant="primary">Turn on dashboard sign-in</Button>}
    >
      Backups contain your access keys, so palaia only offers them after you sign in.
    </Callout>
    <Callout tone="info" title="Search index: 12 of 40 notes ready">
      Search already works; the rest follows in a minute.
    </Callout>
    <Callout tone="ok" title="First note saved">
      Setup took 10 min 16 s.
    </Callout>
    <Callout tone="error" title="Couldn't load your memories" actions={<Button size="sm">Try again</Button>}>
      palaia answered with an error.
    </Callout>
    <Callout tone="neutral" title="Automatic backups are off" />
  </div>
);

export const Disclosures: Story = () => (
  <div className="stack" style={{ maxWidth: 640 }}>
    <Disclosure summary="What's included?">
      <p>
        All memories and their history, palaia's settings, your sign-in, every AI app's access
        key, and keys saved for connected tools.
      </p>
    </Disclosure>
    <Disclosure summary="Advanced" section>
      <p>Tool set: default</p>
    </Disclosure>
  </div>
);

export const Dialogs: Story = () => {
  const [form, setForm] = useState(false);
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="row">
      <Button variant="primary" onClick={() => setForm(true)}>
        New memory
      </Button>
      <Button variant="destructive" onClick={() => setConfirm(true)}>
        Revoke access
      </Button>
      <Dialog
        open={form}
        onClose={() => setForm(false)}
        size="form"
        title="New memory"
        description="A memory is a folder of notes your AI apps read and write."
        footer={
          <>
            <Button onClick={() => setForm(false)}>Cancel</Button>
            <Button variant="primary">Create memory</Button>
          </>
        }
      >
        <LabeledInput label="Name" placeholder="work" />
        <LabeledInput label="What it's for" optional />
      </Dialog>
      <ConfirmDialog
        open={confirm}
        onCancel={() => setConfirm(false)}
        onConfirm={() => setConfirm(false)}
        title="Revoke access for Claude Code CLI?"
        confirmLabel="Revoke access"
        destructive
      >
        <p>The app stops working with palaia right away. You can connect it again later.</p>
      </ConfirmDialog>
    </div>
  );
};
