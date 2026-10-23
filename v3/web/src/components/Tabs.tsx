import type { ReactNode } from "react";

/**
 * Tabs inside one page (Add-ons: Installed · Browse; Automations:
 * Automations · Webhooks). Pair with `useTabParam` so the chosen tab is in
 * the address and survives a reload. For tabs that are separate pages, use
 * `TabLinks`.
 */
export function Tabs<T extends string>({
  label,
  items,
  value,
  onChange,
  idPrefix = "tab",
}: {
  /** What the tabs switch between, for screen readers. */
  label: string;
  items: { id: T; label: ReactNode; count?: number }[];
  value: T;
  onChange: (id: T) => void;
  idPrefix?: string;
}) {
  return (
    <div
      className="tabbar"
      role="tablist"
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
        const index = items.findIndex((item) => item.id === value);
        const step = event.key === "ArrowRight" ? 1 : -1;
        const next = items[(index + step + items.length) % items.length];
        onChange(next.id);
        document.getElementById(`${idPrefix}-${next.id}`)?.focus();
      }}
    >
      {items.map((item) => (
        <button
          key={item.id}
          id={`${idPrefix}-${item.id}`}
          type="button"
          role="tab"
          aria-selected={item.id === value}
          aria-controls={`${idPrefix}-${item.id}-panel`}
          tabIndex={item.id === value ? 0 : -1}
          onClick={() => onChange(item.id)}
        >
          {item.label}
          {item.count ? <span className="nav__count">{item.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/** The panel for one tab: `<TabPanel idPrefix="tab" id="installed">`. */
export function TabPanel({
  id,
  idPrefix = "tab",
  children,
}: {
  id: string;
  idPrefix?: string;
  children: ReactNode;
}) {
  return (
    <div role="tabpanel" id={`${idPrefix}-${id}-panel`} aria-labelledby={`${idPrefix}-${id}`}>
      {children}
    </div>
  );
}
