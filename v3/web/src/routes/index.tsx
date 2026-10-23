import { Suspense } from "react";
import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { AppShell, type PageHandle } from "../shell/AppShell";
import { Home } from "./Home";
import {
  About,
  Agents,
  AiApps,
  Automations,
  Backups,
  Clients,
  Explorer,
  Exposure,
  Marketplace,
  Memories,
  Onboarding,
  ReviewQueue,
  SettingsHub,
  Telegram,
  ToolProfiles,
} from "./lazyScreens";
import { Redirect } from "./Redirect";
import { NotFound, RouteError } from "./RouteError";
import { ScreenLoading } from "./ScreenLoading";

/** Old address → new address (issue 570). Bookmarks, links in older docs and the
 * MCP apps' "open in the dashboard" links keep working; the query string and
 * hash travel along. */
export const REDIRECTS: Record<string, string> = {
  "/explorer": "/memories",
  "/review-queue": "/memories/review",
  "/clients": "/apps",
  "/agents": "/apps/sessions",
  "/tools": "/settings/advanced",
  "/marketplace": "/add-ons",
  "/exposure": "/settings/access",
  "/backups": "/settings/backups",
  "/telegram": "/settings/telegram",
};

/** Every page renders its own `PageHeader` (title, one line, its primary
 * action); the handle's title names the browser tab. */
function page(title: string): { handle: PageHandle } {
  return { handle: { title, ownHeader: true } };
}

/** The route table — exported so tests can mount it in a memory router. */
export const routes: RouteObject[] = [
  // First-run setup is a full-page flow outside the app shell.
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
        // matches — renders its message *inside* the shell (issue 379).
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Home />, ...page("Overview") },
          {
            path: "memories",
            element: <Memories />,
            ...page("Memories"),
            children: [
              { index: true, element: <Explorer /> },
              { path: "review", element: <ReviewQueue /> },
            ],
          },
          {
            path: "apps",
            element: <AiApps />,
            ...page("AI apps"),
            children: [
              { index: true, element: <Clients /> },
              { path: "sessions", element: <Agents /> },
            ],
          },
          {
            path: "add-ons",
            element: <Marketplace />,
            ...page("Add-ons"),
          },
          {
            path: "automations",
            element: <Automations />,
            ...page("Automations"),
          },
          {
            path: "settings",
            children: [
              { index: true, element: <SettingsHub />, ...page("Settings") },
              {
                path: "access",
                element: <Exposure />,
                ...page("Access & sign-in"),
              },
              {
                path: "backups",
                element: <Backups />,
                ...page("Backups"),
              },
              {
                path: "telegram",
                element: <Telegram />,
                ...page("Telegram"),
              },
              {
                path: "advanced",
                element: <ToolProfiles />,
                ...page("Advanced"),
              },
              {
                path: "about",
                element: <About />,
                ...page("About & updates"),
              },
            ],
          },
          ...Object.entries(REDIRECTS).map(([from, to]) => ({
            path: from.slice(1),
            element: <Redirect to={to} />,
          })),
          { path: "*", element: <NotFound />, ...page("Page not found") },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
