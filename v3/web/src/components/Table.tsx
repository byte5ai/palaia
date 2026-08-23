import type { ReactNode } from "react";

export interface Column<Row> {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  /** Right-aligns a numeric/mono column via a per-cell class if given. */
  cellClassName?: string;
}

/** Hairline rows, no zebra, mono uppercase micro-headers, horizontally
 * scrollable in its own wrapper (system.md §2, Data display). */
export function Table<Row extends { id: string | number }>({
  columns,
  rows,
  caption,
}: {
  columns: Column<Row>[];
  rows: Row[];
  /** Visually hidden — an accessible name for the table. */
  caption: string;
}) {
  return (
    <div className="table-wrap scrollpane">
      <table className="table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {columns.map((column) => (
                <td key={column.key} className={column.cellClassName}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
