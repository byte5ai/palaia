/**
 * Theme + accent control (SPEC-109), binding Lume's own attributes.
 *
 * `data-mode` follows the system preference until the person picks one
 * explicitly (lume/README.md decision 2: "system default, manual
 * override"); `data-accent` defaults to unset, which tokens.css already
 * binds to atelier (palaia's default, per the same README). The choice is
 * remembered per-browser in localStorage — a per-viewer convenience, not
 * data that needs to sync anywhere (Artifact rules on browser storage
 * apply the same reasoning here: never let a blocked/absent store break
 * rendering).
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
export type AccentPalette = "atelier" | "lagoon" | "petrol";

interface ThemeContextValue {
  mode: ThemeMode;
  accent: AccentPalette;
  setMode: (mode: ThemeMode) => void;
  setAccent: (accent: AccentPalette) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const MODE_KEY = "palaia.theme.mode";
const ACCENT_KEY = "palaia.theme.accent";

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    if (value && (allowed as readonly string[]).includes(value)) {
      return value as T;
    }
  } catch {
    // localStorage can throw (private browsing, blocked site data) —
    // fall back silently, per Artifact browser-storage guidance.
  }
  return fallback;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() =>
    readStored(MODE_KEY, ["system", "light", "dark"] as const, "system"),
  );
  const [accent, setAccentState] = useState<AccentPalette>(() =>
    readStored(ACCENT_KEY, ["atelier", "lagoon", "petrol"] as const, "atelier"),
  );

  useEffect(() => {
    const root = document.documentElement;
    if (mode === "system") {
      root.removeAttribute("data-mode");
    } else {
      root.setAttribute("data-mode", mode);
    }
  }, [mode]);

  useEffect(() => {
    const root = document.documentElement;
    if (accent === "atelier") {
      root.removeAttribute("data-accent");
    } else {
      root.setAttribute("data-accent", accent);
    }
  }, [accent]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      // per-viewer convenience only; a blocked store just means the next
      // visit re-defaults to "system"
    }
  }, []);

  const setAccent = useCallback((next: AccentPalette) => {
    setAccentState(next);
    try {
      window.localStorage.setItem(ACCENT_KEY, next);
    } catch {
      // see setMode
    }
  }, []);

  const value = useMemo(
    () => ({ mode, accent, setMode, setAccent }),
    [mode, accent, setMode, setAccent],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}
