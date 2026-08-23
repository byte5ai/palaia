/**
 * Nav + chrome icons — inline SVG, 24-unit grid, 1.5px stroke,
 * currentColor, round caps (system.md §1.5). Paths lifted from the
 * SPEC-005 mockups (v3/docs/design/mockups/home.html) for visual parity,
 * not redrawn.
 */
import type { SVGProps } from "react";

function Icon({ children, className, ...rest }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      className={["icon", className ?? ""].filter(Boolean).join(" ")}
      viewBox="0 0 24 24"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function HomeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M3 10.6 12 4l9 6.6V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    </Icon>
  );
}

export function ExplorerIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M6 3.5h8l4.5 4.5V20.5H6z" />
      <path d="M14 3.5V8h4.5" />
      <path d="M9 12.5h6M9 16h4" />
    </Icon>
  );
}

export function InboxIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 13.5h4l1.2 2.5h5.6l1.2-2.5h4" />
      <path d="M4 13.5 6.7 5h10.6L20 13.5V20H4z" />
    </Icon>
  );
}

export function ReviewIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M8.3 12.4l2.7 2.7 4.7-5.2" />
    </Icon>
  );
}

export function VaultsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="4.5" width="17" height="4.5" rx="1.2" />
      <path d="M5.5 9v10.5h13V9" />
      <path d="M10 13h4" />
    </Icon>
  );
}

export function ClientsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M9 3v4.5M15 3v4.5" />
      <path d="M6.8 7.5h10.4v3.2a5.2 5.2 0 0 1-10.4 0z" />
      <path d="M12 16v5" />
    </Icon>
  );
}

export function ToolsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.4" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.4" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.4" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.4" />
    </Icon>
  );
}

export function AutomationsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M13.2 3 5.5 14h5l-1 7 8.2-11.2h-5.1z" />
    </Icon>
  );
}

export function HealthIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M3 12.5h3.8l2.2-5.5 3.4 11 2.2-5.5H21" />
    </Icon>
  );
}

export function SettingsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="3.1" />
      <path d="M12 4v2M12 18v2M4 12h2M18 12h2M6.7 6.7l1.4 1.4M15.9 15.9l1.4 1.4M17.3 6.7l-1.4 1.4M8.1 15.9l-1.4 1.4" />
    </Icon>
  );
}

export function SearchIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="11" cy="11" r="6.2" />
      <path d="M15.6 15.6 20 20" />
    </Icon>
  );
}

/** Claude Code CLI's mark (onboarding.html / connect-client.html). */
export function SparkleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M12 3.5l1.9 4.9 4.9 1.9-4.9 1.9L12 17.1l-1.9-4.9-4.9-1.9 4.9-1.9z" />
    </Icon>
  );
}

/** claude.ai / ChatGPT's mark — a connector, for anything that reaches the
 * hub over the web rather than running on the operator's own machine. */
export function LinkIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M10 13.8a3.6 3.6 0 0 0 5.1 0l2.6-2.6a3.6 3.6 0 0 0-5.1-5.1l-1.2 1.2" />
      <path d="M14 10.2a3.6 3.6 0 0 0-5.1 0l-2.6 2.6a3.6 3.6 0 0 0 5.1 5.1l1.2-1.2" />
    </Icon>
  );
}

export function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4.5 12.5 10 18 19.5 6.5" />
    </Icon>
  );
}

export function ArrowRightIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4.5 12h14M13 6.5l5.5 5.5L13 17.5" />
    </Icon>
  );
}

export function CopyIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="9" y="9" width="10.5" height="10.5" rx="2" />
      <path d="M15 9V6.5a2 2 0 0 0-2-2H6.5a2 2 0 0 0-2 2V13a2 2 0 0 0 2 2H9" />
    </Icon>
  );
}

export function InfoIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 11v5.2M12 7.9h.01" />
    </Icon>
  );
}

export function WarningIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M12 4.2 21 20H3z" />
      <path d="M12 10v4.2M12 17.2h.01" />
    </Icon>
  );
}
