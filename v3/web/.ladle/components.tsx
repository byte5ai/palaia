import type { GlobalProvider } from "@ladle/react";
import { useEffect } from "react";

import { ToastProvider } from "../src/components";
import { ThemeProvider } from "../src/lib/theme";
import "../src/index.css";

/**
 * Bridges Ladle's own light/dark toggle (which sets `data-theme` on
 * `<html>`) onto Lume's `data-mode` attribute (system.md §1, decision 2)
 * — every story renders through the same token switch the real app
 * uses, rather than a second theme mechanism.
 */
function ModeBridge({ theme }: { theme: string }) {
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") {
      root.removeAttribute("data-mode");
    } else {
      root.setAttribute("data-mode", theme);
    }
  }, [theme]);
  return null;
}

export const GlobalProvider: GlobalProvider = ({ children, globalState }) => (
  <ThemeProvider>
    <ToastProvider>
      <ModeBridge theme={globalState.theme} />
      <div style={{ background: "var(--bg-canvas-top)", minHeight: "100%", padding: "var(--space-6)" }}>
        {children}
      </div>
    </ToastProvider>
  </ThemeProvider>
);
