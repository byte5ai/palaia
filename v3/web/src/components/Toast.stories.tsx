import type { Story } from "@ladle/react";

import { Button } from "./Button";
import { useToast } from "./Toast";

function Demo() {
  const toast = useToast();
  return (
    <div className="row row--wrap">
      <Button
        onClick={() =>
          toast.show("Profile updated — Codex now sees 6 tools.")
        }
      >
        Show a toast
      </Button>
      <Button
        onClick={() =>
          toast.show("Claude Code CLI wrote Billing service.", {
            action: { label: "Undo", onClick: () => {} },
          })
        }
      >
        Show a toast with undo
      </Button>
    </div>
  );
}

export default {
  title: "Feedback / Toast",
};

/** ToastProvider already wraps every story (see .ladle/components.tsx),
 * matching how the real app mounts it once at the root. */
export const Default: Story = () => <Demo />;
