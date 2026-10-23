import type { GlobalProvider } from "@ladle/react";
import { useEffect } from "react";

import { ToastProvider } from "../src/components";
import { ThemeProvider, useTheme } from "../src/lib/theme";
import "../src/index.css";

/**
 * Hands Ladle's light/dark toggle to the app's own ThemeProvider, so every
 * story renders through the same `data-theme` switch the dashboard uses.
 */
function ThemeBridge({ theme }: { theme: string }) {
  const { setMode } = useTheme();
  useEffect(() => {
    setMode(theme === "light" || theme === "dark" ? theme : "system");
  }, [theme, setMode]);
  return null;
}

export const GlobalProvider: GlobalProvider = ({ children, globalState }) => (
  <ThemeProvider>
    <ToastProvider>
      <ThemeBridge theme={globalState.theme} />
      <div style={{ background: "var(--canvas)", minHeight: "100%", padding: "var(--space-6)" }}>
        {children}
      </div>
    </ToastProvider>
  </ThemeProvider>
);
