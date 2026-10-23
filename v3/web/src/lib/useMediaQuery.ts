import { useEffect, useState } from "react";

/** Whether a media query matches, updated live. `false` where the browser
 * (or the test environment) has no `matchMedia`. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener?.("change", onChange);
    return () => list.removeEventListener?.("change", onChange);
  }, [query]);
  return matches;
}

/** The phone layout: app bar and drawer instead of the sidebar. */
export const PHONE_QUERY = "(max-width: 767px)";
