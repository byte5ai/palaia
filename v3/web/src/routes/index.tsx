import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { NAV_GROUPS } from "../shell/navConfig";
import { Automations } from "./Automations";
import { Clients } from "./Clients";
import { ComingSoon } from "./ComingSoon";
import { Explorer } from "./Explorer";
import { Exposure } from "./Exposure";
import { Home } from "./Home";
import { Marketplace } from "./Marketplace";
import { Onboarding } from "./onboarding/Onboarding";
import { Settings } from "./Settings";
import { ToolProfiles } from "./ToolProfiles";

// Paths SPEC-110/SPEC-201/SPEC-204/SPEC-205/SPEC-305/SPEC-304 build a real
// screen for — everything else in NAV_GROUPS still falls through to
// ComingSoon below, so no nav destination is ever a dead link (SPEC-109's
// rule, carried forward).
const BUILT_PATHS = new Set([
  "/",
  "/explorer",
  "/clients",
  "/automations",
  "/exposure",
  "/settings",
  "/tools",
  "/marketplace",
]);

const placeholderRoutes = NAV_GROUPS.flatMap((group) => group.items)
  .filter((item) => !BUILT_PATHS.has(item.path))
  .map((item) => ({
    path: item.path,
    element: <ComingSoon label={item.label} />,
  }));

export const router = createBrowserRouter([
  // The onboarding wizard is deliberately outside AppShell: it is a
  // full-page flow with its own rail (onboarding.html's `.wiz`), not a
  // destination inside the app's own navigation.
  { path: "/onboarding", element: <Onboarding /> },
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Home /> },
      { path: "explorer", element: <Explorer /> },
      { path: "clients", element: <Clients /> },
      { path: "automations", element: <Automations /> },
      { path: "exposure", element: <Exposure /> },
      { path: "settings", element: <Settings /> },
      { path: "tools", element: <ToolProfiles /> },
      { path: "marketplace", element: <Marketplace /> },
      ...placeholderRoutes,
    ],
  },
]);
