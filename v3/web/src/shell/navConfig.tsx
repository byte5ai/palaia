import type { ComponentType, SVGProps } from "react";

import {
  AutomationsIcon,
  ClientsIcon,
  HomeIcon,
  MarketplaceIcon,
  SettingsIcon,
  VaultsIcon,
} from "./icons";

export interface NavItemConfig {
  path: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Match the path exactly (Overview), not as a prefix. */
  end?: boolean;
  /** A live count from the event stream next to the item: memory notes
   * written since the page was opened (SPEC-109: a change on disk updates
   * the count without a reload). */
  liveBadge?: "vaultChanges";
}

/**
 * Five places, organised around what people do: see whether palaia is
 * fine, find what it remembered, connect AI apps, add tools, automate.
 * Everything about the server itself is under Settings, at the bottom.
 */
export const NAV_ITEMS: NavItemConfig[] = [
  { path: "/", label: "Overview", icon: HomeIcon, end: true },
  { path: "/memories", label: "Memories", icon: VaultsIcon, liveBadge: "vaultChanges" },
  { path: "/apps", label: "AI apps", icon: ClientsIcon },
  { path: "/add-ons", label: "Add-ons", icon: MarketplaceIcon },
  { path: "/automations", label: "Automations", icon: AutomationsIcon },
];

export const SETTINGS_ITEM: NavItemConfig = {
  path: "/settings",
  label: "Settings",
  icon: SettingsIcon,
};
