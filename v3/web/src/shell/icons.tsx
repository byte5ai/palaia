/**
 * Nav and chrome icons: inline SVG on a 24-unit grid, stroked in
 * currentColor with round caps (system.md §1.5). One weight everywhere.
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

/** SPEC-307's notification bell (topbar). */
export function BellIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M6.5 15.5V11a5.5 5.5 0 0 1 11 0v4.5l1.5 2H5z" />
      <path d="M10 19.5a2 2 0 0 0 4 0" />
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

/** Error: the info circle with an exclamation mark. */
export function ErrorIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 7.8v5.2M12 16.1h.01" />
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

/** SPEC-304: the marketplace nav item — a storefront glyph. */
export function MarketplaceIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 9.5 5.5 4h13L20 9.5" />
      <path d="M4 9.5h16V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z" />
      <path d="M9 9.5a3 3 0 0 0 6 0" />
    </Icon>
  );
}

/** SPEC-405: the agents nav item — two linked presence dots (the directory
 * plus the messenger flow between them). */
export function AgentsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="8" cy="8" r="3" />
      <circle cx="16" cy="16" r="3" />
      <path d="M10.2 10.2 13.8 13.8" />
    </Icon>
  );
}

/** Issue 439: the Telegram nav item — a paper plane, the one glyph people
 * already read as "Telegram" without a logo. */
export function TelegramIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M20.5 4 3.5 10.8l6.2 2.3L20.5 4z" />
      <path d="M20.5 4 17.3 19.5l-7.6-6.4" />
      <path d="M9.7 13.1V19l3-3.3" />
    </Icon>
  );
}

/** Issue 438: the backup screen — a box with something going into it. */
export function BackupIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 9.5v9a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-9" />
      <path d="M3.5 6.5h17v3h-17z" />
      <path d="M12 3v7.5M9.5 8 12 10.5 14.5 8" />
    </Icon>
  );
}

export function ChevronRightIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M9.5 6.5 15 12l-5.5 5.5" />
    </Icon>
  );
}

export function ChevronLeftIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M14.5 6.5 9 12l5.5 5.5" />
    </Icon>
  );
}

export function MenuIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </Icon>
  );
}

export function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M6 6l12 12M6 18L18 6" />
    </Icon>
  );
}




export function KeyIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="8" cy="15" r="3.5" />
      <path d="M10.5 12.5 19 4M15.5 7.5l2.5 2.5M13.5 9.5l2 2" />
    </Icon>
  );
}

export function LockIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="5" y="10.5" width="14" height="9.5" rx="2" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    </Icon>
  );
}

export function DownloadIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M12 4v11M7.5 10.5 12 15l4.5-4.5" />
      <path d="M5 19.5h14" />
    </Icon>
  );
}

export function RestartIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M19 12a7 7 0 1 1-2.05-4.95" />
      <path d="M19 4.5V8h-3.5" />
    </Icon>
  );
}

/** Appearance: a half-filled circle. */
export function AppearanceIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 4v16a8 8 0 0 0 0-16z" fill="currentColor" stroke="none" />
    </Icon>
  );
}

/** Advanced settings: sliders. */
export function SlidersIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M5 7h9M18 7h1M5 17h1M10 17h9" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </Icon>
  );
}

export function SignOutIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M14 4.5H6.5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1H14" />
      <path d="M10.5 12H20M16.5 8.5 20 12l-3.5 3.5" />
    </Icon>
  );
}

/**
 * The palaia star: a hub with five connected points. Geometry taken
 * verbatim from the website header (palaia-homepage
 * `components/Header.tsx`, `HubMark`), coloured with the brand token.
 */
export function PalaiaMark({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      {...props}
    >
      <circle cx="12" cy="12" r="3" fill="var(--brand)" />
      <g stroke="var(--brand)" strokeOpacity="0.5" strokeWidth="1.3">
        <line x1="12" y1="12" x2="12" y2="3" />
        <line x1="12" y1="12" x2="20" y2="8" />
        <line x1="12" y1="12" x2="19" y2="18" />
        <line x1="12" y1="12" x2="5" y2="18" />
        <line x1="12" y1="12" x2="4" y2="8" />
      </g>
      <g fill="var(--brand)" fillOpacity="0.85">
        <circle cx="12" cy="3" r="1.7" />
        <circle cx="20" cy="8" r="1.7" />
        <circle cx="19" cy="18" r="1.7" />
        <circle cx="5" cy="18" r="1.7" />
        <circle cx="4" cy="8" r="1.7" />
      </g>
    </svg>
  );
}
