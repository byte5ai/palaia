import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * The selected in-page tab, kept in the address (`?view=webhooks`) so a
 * reload or a shared link opens the same tab. The first id is the default
 * and is left out of the address.
 */
export function useTabParam<T extends string>(
  ids: readonly T[],
  param = "view",
): [T, (next: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(param);
  const value = (ids as readonly string[]).includes(raw ?? "") ? (raw as T) : ids[0];
  const setValue = useCallback(
    (next: T) => {
      setParams(
        (prev) => {
          const updated = new URLSearchParams(prev);
          if (next === ids[0]) updated.delete(param);
          else updated.set(param, next);
          return updated;
        },
        { replace: true },
      );
    },
    [ids, param, setParams],
  );
  return [value, setValue];
}
