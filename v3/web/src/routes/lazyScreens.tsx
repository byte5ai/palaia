import { lazy } from "react";

// Issue 406: every screen used to be imported eagerly, so the first paint
// downloaded one ~460 kB bundle. Home and the shell stay in the entry chunk
// (they are the first paint); every other screen — and what only it
// imports, such as the SKILL.md sources the connect panels inline — loads
// when its route is first visited.
export const Agents = lazy(() =>
  import("./Agents").then((m) => ({ default: m.Agents })),
);
export const Automations = lazy(() =>
  import("./Automations").then((m) => ({ default: m.Automations })),
);
export const Backups = lazy(() =>
  import("./Backups").then((m) => ({ default: m.Backups })),
);
export const Clients = lazy(() =>
  import("./Clients").then((m) => ({ default: m.Clients })),
);
export const Explorer = lazy(() =>
  import("./Explorer").then((m) => ({ default: m.Explorer })),
);
export const Exposure = lazy(() =>
  import("./Exposure").then((m) => ({ default: m.Exposure })),
);
export const Marketplace = lazy(() =>
  import("./Marketplace").then((m) => ({ default: m.Marketplace })),
);
export const Onboarding = lazy(() =>
  import("./onboarding/Onboarding").then((m) => ({ default: m.Onboarding })),
);
export const ReviewQueue = lazy(() =>
  import("./ReviewQueue").then((m) => ({ default: m.ReviewQueue })),
);
export const Settings = lazy(() =>
  import("./Settings").then((m) => ({ default: m.Settings })),
);
export const Telegram = lazy(() =>
  import("./Telegram").then((m) => ({ default: m.Telegram })),
);
export const ToolProfiles = lazy(() =>
  import("./ToolProfiles").then((m) => ({ default: m.ToolProfiles })),
);
