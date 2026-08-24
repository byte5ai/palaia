import type { ComponentType, SVGProps } from "react";

import {
  AutomationsIcon,
  ClientsIcon,
  ExplorerIcon,
  HealthIcon,
  HomeIcon,
  InboxIcon,
  LinkIcon,
  ReviewIcon,
  SettingsIcon,
  ToolsIcon,
  VaultsIcon,
} from "./icons";

export interface NavItemConfig {
  path: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Nav item id this SPEC's SSE-backed badge attaches to (SPEC-109
   * acceptance criterion: a vault change updates the explorer badge
   * without reload). Feature screens (SPEC-110) will bring their own
   * counts for inbox/review — this SPEC only wires the one it can back
   * with a real event. */
  liveBadge?: "vaultChanges";
}

export interface NavGroupConfig {
  label: string;
  items: NavItemConfig[];
}

export const NAV_GROUPS: NavGroupConfig[] = [
  {
    label: "Overview",
    items: [{ path: "/", label: "Home", icon: HomeIcon }],
  },
  {
    label: "Memory",
    items: [
      { path: "/explorer", label: "Explorer", icon: ExplorerIcon, liveBadge: "vaultChanges" },
      { path: "/inbox", label: "Inbox", icon: InboxIcon },
      { path: "/review-queue", label: "Review queue", icon: ReviewIcon },
      { path: "/vaults", label: "Vaults", icon: VaultsIcon },
    ],
  },
  {
    label: "Connections",
    items: [
      { path: "/clients", label: "Clients", icon: ClientsIcon },
      { path: "/tools", label: "Tools & skills", icon: ToolsIcon },
    ],
  },
  {
    label: "System",
    items: [
      { path: "/automations", label: "Automations", icon: AutomationsIcon },
      { path: "/exposure", label: "Access mode", icon: LinkIcon },
      { path: "/health", label: "Health", icon: HealthIcon },
      { path: "/settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];
