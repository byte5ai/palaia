import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { NAV_GROUPS } from "../shell/navConfig";
import { Agents } from "./Agents";
import { Automations } from "./Automations";
import { Clients } from "./Clients";
import { ComingSoon } from "./ComingSoon";
import { Explorer } from "./Explorer";
import { Exposure } from "./Exposure";
import { Home } from "./Home";
import { Marketplace } from "./Marketplace";
import { Onboarding } from "./onboarding/Onboarding";
import { ReviewQueue } from "./ReviewQueue";
import { NotFound, RouteError } from "./RouteError";
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
  "/agents",
  "/review-queue",
]);

const placeholderRoutes = NAV_GROUPS.flatMap((group) => group.items)
  .filter((item) => !BUILT_PATHS.has(item.path))
  .map((item) => ({
    path: item.path,
    element: <ComingSoon label={item.label} />,
  }));

/** The route table — exported so tests can mount it in a memory router. */
export const routes: RouteObject[] = [
  // The onboarding wizard is deliberately outside AppShell: it is a
  // full-page flow with its own rail (onboarding.html's `.wiz`), not a
  // destination inside the app's own navigation.
  { path: "/onboarding", element: <Onboarding />, errorElement: <RouteError /> },
  {
    path: "/",
    element: <AppShell />,
    // Issue 379: an error the shell itself cannot render past still gets
    // a page in our words rather than React Router's default one.
    errorElement: <RouteError />,
    children: [
      {
        // A pathless layer so a screen that throws — or a URL nothing
        // matches — renders its message *inside* the shell, navigation and
        // health intact (issue 379).
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Home /> },
          { path: "explorer", element: <Explorer /> },
          { path: "clients", element: <Clients /> },
          { path: "automations", element: <Automations /> },
          { path: "exposure", element: <Exposure /> },
          { path: "settings", element: <Settings /> },
          { path: "tools", element: <ToolProfiles /> },
          { path: "marketplace", element: <Marketplace /> },
          { path: "agents", element: <Agents /> },
          { path: "review-queue", element: <ReviewQueue /> },
          ...placeholderRoutes,
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
