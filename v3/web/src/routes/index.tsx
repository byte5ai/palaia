import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "../shell/AppShell";
import { NAV_GROUPS } from "../shell/navConfig";
import { ComingSoon } from "./ComingSoon";
import { Home } from "./Home";

const placeholderRoutes = NAV_GROUPS.flatMap((group) => group.items)
  .filter((item) => item.path !== "/")
  .map((item) => ({
    path: item.path,
    element: <ComingSoon label={item.label} />,
  }));

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [{ index: true, element: <Home /> }, ...placeholderRoutes],
  },
]);
