/**
 * Appearance: System, Light or Dark.
 *
 * tokens.css follows the system preference unless `data-theme` on <html>
 * pins one ("light" or "dark"). "System" removes the attribute. The choice is
 * remembered per browser in localStorage, a per-viewer convenience: a blocked
 * or empty store just means the next visit follows the system again.
 */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type ThemeMode = "system" | "light" | "dark";

interface ThemeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const MODE_KEY = "palaia.theme.mode";
const MODES: readonly ThemeMode[] = ["system", "light", "dark"];

function readStoredMode(): ThemeMode {
  try {
    const value = window.localStorage.getItem(MODE_KEY);
    if (value && (MODES as readonly string[]).includes(value)) return value as ThemeMode;
  } catch {
    // localStorage can throw (private browsing, blocked site data).
  }
  return "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode);

  useEffect(() => {
    const root = document.documentElement;
    if (mode === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", mode);
    }
  }, [mode]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      // per-viewer convenience only
    }
  }, []);

  const value = useMemo(() => ({ mode, setMode }), [mode, setMode]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}
