import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { NAV_GROUPS } from "../shell/navConfig";
import { Automations } from "./Automations";
import { Clients } from "./Clients";
import { ComingSoon } from "./ComingSoon";
import { Explorer } from "./Explorer";
import { Home } from "./Home";
import { Onboarding } from "./onboarding/Onboarding";

// Paths SPEC-110/SPEC-201 build a real screen for — everything else in
// NAV_GROUPS still falls through to ComingSoon below, so no nav
// destination is ever a dead link (SPEC-109's rule, carried forward).
const BUILT_PATHS = new Set(["/", "/explorer", "/clients", "/automations"]);

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
      ...placeholderRoutes,
    ],
  },
]);
