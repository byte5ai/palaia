/**
 * The base components' contracts from system.md §2 — the parts a screen
 * relies on without looking: the optional marker, a dialog that traps and
 * returns focus, rows that are links or buttons, steps that say their state.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Callout } from "./Callout";
import { ConfirmDialog, Dialog } from "./Dialog";
import { ErrorState } from "./EmptyState";
import { Field, LabeledInput } from "./Field";
import { ListRow } from "./ListRow";
import { StatusPill } from "./StatusPill";
import { Stepper, StepperPanel } from "./Stepper";

describe("Field", () => {
  it("marks optional fields, and only those", () => {
    render(
      <>
        <LabeledInput label="Name" />
        <LabeledInput label="What it's for" optional />
      </>,
    );
    expect(screen.getAllByText("Optional")).toHaveLength(1);
    expect(screen.getByLabelText(/what it's for/i)).toBeInstanceOf(HTMLInputElement);
    expect(screen.getByLabelText(/^name$/i)).toBeInstanceOf(HTMLInputElement);
  });

  it("shows the error instead of the helper", () => {
    render(
      <Field label="Address" hint="Starts with https://" error="Enter the full address.">
        <input />
      </Field>,
    );
    expect(screen.getByText("Enter the full address.")).toBeInTheDocument();
    expect(screen.queryByText("Starts with https://")).not.toBeInTheDocument();
  });
});

describe("StatusPill", () => {
  it("always carries the word, in its tone", () => {
    render(<StatusPill tone="warn">Needs Cloud mode</StatusPill>);
    const pill = screen.getByText("Needs Cloud mode");
    expect(pill).toHaveClass("pill", "pill--warn");
  });
});

describe("Button", () => {
  it("is disabled while loading and keeps its verb", () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Preparing the file…
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Preparing the file…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});

describe("ListRow", () => {
  it("is a link with a chevron when it goes somewhere", () => {
    render(
      <MemoryRouter>
        <ListRow to="/settings/backups" title="Backups" description="Last backup 2 days ago" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /backups/i });
    expect(link).toHaveAttribute("href", "/settings/backups");
    expect(link.querySelector(".listrow__chevron")).not.toBeNull();
  });

  it("is a button when it does something", () => {
    const onClick = vi.fn();
    render(<ListRow onClick={onClick} title="Claude Code CLI" />);
    fireEvent.click(screen.getByRole("button", { name: /claude code cli/i }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("is neither for a setting row: the control is the target", () => {
    render(<ListRow setting title="Appearance" trailing={<button type="button">Dark</button>} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});

describe("Callout and ErrorState", () => {
  it("an error says what failed and offers Try again — it never looks empty", () => {
    const onRetry = vi.fn();
    render(
      <ErrorState title="Couldn't load your memories" details="500" onRetry={onRetry}>
        palaia answered with an error.
      </ErrorState>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load your memories");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("a callout holds the action that fixes the state", () => {
    render(
      <Callout tone="warn" title="Backups need dashboard sign-in" actions={<button type="button">Turn on dashboard sign-in</button>} />,
    );
    expect(screen.getByRole("button", { name: "Turn on dashboard sign-in" })).toBeInTheDocument();
  });
});

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        New memory
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="New memory"
        footer={
          <>
            <button type="button" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="button">Create memory</button>
          </>
        }
      >
        <LabeledInput label="Name" />
      </Dialog>
    </>
  );
}

describe("Dialog", () => {
  it("is a labelled modal, focuses its first field, closes on Escape and returns focus", () => {
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "New memory" });
    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "New memory" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByLabelText("Name")).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("keeps Tab inside the dialog", () => {
    render(<DialogHarness />);
    fireEvent.click(screen.getByRole("button", { name: "New memory" }));
    const last = screen.getByRole("button", { name: "Create memory" });
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });

  it("a destructive confirm names its action and uses the filled red button", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        onCancel={() => {}}
        onConfirm={onConfirm}
        title="Revoke access for Claude Code CLI?"
        confirmLabel="Revoke access"
        destructive
      />,
    );
    const confirm = screen.getByRole("button", { name: "Revoke access" });
    expect(confirm).toHaveClass("btn--danger");
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});

describe("Stepper", () => {
  it("counts the steps and says which are done, current or need attention", () => {
    render(
      <Stepper
        currentIndex={2}
        steps={[
          { id: "account", label: "Your account", state: "done" },
          { id: "where", label: "Where you'll use palaia", state: "attention" },
          { id: "memory", label: "Your first memory", state: "current" },
          { id: "app", label: "Connect an AI app", state: "todo" },
          { id: "done", label: "Done", state: "todo" },
        ]}
      >
        <StepperPanel title="Create your first memory" />
      </Stepper>,
    );
    expect(screen.getByText("Step 3 of 5")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "3");
    const steps = screen.getAllByRole("listitem");
    expect(steps[0]).toHaveTextContent("(done)");
    expect(steps[1]).toHaveTextContent("(needs attention)");
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("heading", { name: "Create your first memory" })).toBeInTheDocument();
  });
});
