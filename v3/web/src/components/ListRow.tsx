import type { ReactNode } from "react";

export function ListRow({
  selected = false,
  onClick,
  children,
}: {
  selected?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      className={["listrow", selected ? "listrow--selected" : ""].filter(Boolean).join(" ")}
      onClick={onClick}
      type={onClick ? "button" : undefined}
      aria-current={selected ? "true" : undefined}
      style={onClick ? { width: "100%", textAlign: "left", cursor: "pointer" } : undefined}
    >
      {children}
    </Tag>
  );
}

export function ListRowTitle({ children }: { children: ReactNode }) {
  return <span className="listrow__title">{children}</span>;
}

export function ListRowMeta({ children }: { children: ReactNode }) {
  return <span className="listrow__meta">{children}</span>;
}
