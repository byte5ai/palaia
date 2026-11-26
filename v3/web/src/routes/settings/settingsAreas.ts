/** The areas of Settings, in navigation order. Each one is a route under
 * `/settings` (`routes/index.tsx`); a test keeps the two lists equal. */
export const SETTINGS_AREAS: { to: string; label: string; end?: boolean }[] = [
  { to: "/settings", label: "General", end: true },
  { to: "/settings/access", label: "Access & sign-in" },
  { to: "/settings/backups", label: "Backups" },
  { to: "/settings/telegram", label: "Telegram" },
  { to: "/settings/advanced", label: "Advanced" },
  { to: "/settings/about", label: "About & updates" },
];
