import type { ReactNode } from "react";

import { ChevronRightIcon } from "../shell/icons";

/**
 * Detail on demand: "What's included?", "Advanced", "Troubleshooting".
 * A native <details>, so it opens with the keyboard and works without
 * script. `section` draws a divider above it, for an Advanced block at
 * the end of a card or form.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  section = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  section?: boolean;
}) {
  return (
    <details
      className={["disclosure", section ? "disclosure--section" : ""].filter(Boolean).join(" ")}
      open={defaultOpen || undefined}
    >
      <summary>
        <ChevronRightIcon className="icon--sm disclosure__chevron" />
        {summary}
      </summary>
      <div className="disclosure__body">{children}</div>
    </details>
  );
}
