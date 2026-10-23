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

const SETTINGS_BACK = { to: "/settings", label: "Settings" };

function page(handle: PageHandle): { handle: PageHandle } {
  return { handle };
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
          { index: true, element: <Home />, ...page({ title: "Overview", ownHeader: true }) },
          {
            path: "memories",
            element: <Memories />,
            ...page({
              title: "Memories",
              description: "What your AI apps saved, and what palaia wants you to check.",
            }),
            children: [
              { index: true, element: <Explorer /> },
              { path: "review", element: <ReviewQueue /> },
            ],
          },
          {
            path: "apps",
            element: <AiApps />,
            ...page({
              title: "AI apps",
              description: "Connect the apps you use, and see which ones are working.",
            }),
            children: [
              { index: true, element: <Clients /> },
              { path: "sessions", element: <Agents /> },
            ],
          },
          {
            path: "add-ons",
            element: <Marketplace />,
            ...page({
              title: "Add-ons",
              description: "Install a tool once and every connected AI app can use it.",
            }),
          },
          {
            path: "automations",
            element: <Automations />,
            ...page({
              title: "Automations",
              description: "Let palaia act when something happens in your memories.",
            }),
          },
          {
            path: "settings",
            children: [
              { index: true, element: <SettingsHub />, ...page({ title: "Settings" }) },
              {
                path: "access",
                element: <Exposure />,
                ...page({ title: "Access & sign-in", back: SETTINGS_BACK }),
              },
              {
                path: "backups",
                element: <Backups />,
                ...page({ title: "Backups", back: SETTINGS_BACK }),
              },
              {
                path: "telegram",
                element: <Telegram />,
                ...page({ title: "Telegram", back: SETTINGS_BACK }),
              },
              {
                path: "advanced",
                element: <ToolProfiles />,
                ...page({ title: "Advanced", back: SETTINGS_BACK }),
              },
              {
                path: "about",
                element: <About />,
                ...page({ title: "About & updates", back: SETTINGS_BACK }),
              },
            ],
          },
          ...Object.entries(REDIRECTS).map(([from, to]) => ({
            path: from.slice(1),
            element: <Redirect to={to} />,
          })),
          { path: "*", element: <NotFound />, ...page({ title: "Page not found", ownHeader: true }) },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
