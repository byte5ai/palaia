import { Suspense } from "react";
import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { NAV_GROUPS } from "../shell/navConfig";
import { ComingSoon } from "./ComingSoon";
import { Home } from "./Home";
import {
  Agents,
  Automations,
  Clients,
  Explorer,
  Exposure,
  Marketplace,
  Onboarding,
  ReviewQueue,
  Settings,
  Telegram,
  ToolProfiles,
} from "./lazyScreens";
import { NotFound, RouteError } from "./RouteError";
import { ScreenLoading } from "./ScreenLoading";

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
  "/telegram",
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
  {
    path: "/onboarding",
    element: (
      <Suspense fallback={<ScreenLoading />}>
        <Onboarding />
      </Suspense>
    ),
    errorElement: <RouteError />,
  },
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
          { path: "telegram", element: <Telegram /> },
          { path: "review-queue", element: <ReviewQueue /> },
          ...placeholderRoutes,
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
