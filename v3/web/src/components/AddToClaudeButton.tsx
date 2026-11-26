import { buttonClass, type ButtonSize } from "./buttonClass";

/** The one-click way into Claude's "Add custom connector" dialog, with the
 * name and the public MCP address already filled in. `href` comes from
 * `claudeInstallLink` and carries nothing else. `noreferrer` keeps the
 * address of this (private) dashboard out of the request Claude receives. */
export function AddToClaudeButton({
  href,
  size = "md",
}: {
  href: string;
  size?: ButtonSize;
}) {
  return (
    <a
      className={buttonClass({ variant: "primary", size })}
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      Add to Claude
    </a>
  );
}
