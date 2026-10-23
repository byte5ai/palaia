import type { Story } from "@ladle/react";

import { Table } from "./Table";

interface ClientRow {
  id: string;
  name: string;
  profile: string;
  lastSeen: string;
}

const rows: ClientRow[] = [
  {
    id: "1",
    name: "Claude Code CLI",
    profile: "coding",
    lastSeen: "6 min ago",
  },
  { id: "2", name: "Claude Desktop", profile: "general", lastSeen: "2 h ago" },
  { id: "3", name: "claude.ai", profile: "general", lastSeen: "1 d ago" },
];

export default {
  title: "Data display / Table",
};

export const Default: Story = () => (
  <Table<ClientRow>
    caption="Connected AI apps"
    columns={[
      { key: "name", header: "AI app", render: (row) => row.name },
      { key: "profile", header: "Tool set", render: (row) => row.profile },
      {
        key: "lastSeen",
        header: "Last request",
        render: (row) => <span className="t-meta">{row.lastSeen}</span>,
      },
    ]}
    rows={rows}
  />
);
