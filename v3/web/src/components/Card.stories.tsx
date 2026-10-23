import type { Story } from "@ladle/react";
import { MemoryRouter } from "react-router-dom";

import { BackupIcon, LockIcon } from "../shell/icons";
import { Button } from "./Button";
import { Card, CardBody, CardFoot, CardHeader } from "./Card";
import { ListRow } from "./ListRow";
import { StatusPill } from "./StatusPill";

export default {
  title: "Surfaces / Card",
};

export const StatusFirst: Story = () => (
  <Card style={{ maxWidth: 560 }}>
    <CardHeader
      title="Backup"
      description="Download a copy of your memories and settings."
      actions={<StatusPill tone="ok">Backed up</StatusPill>}
    />
    <CardBody>
      <p className="t-sm t-muted">
        Includes private data and access keys. Anyone with the file can use them, so store it
        like a password.
      </p>
    </CardBody>
    <CardFoot>
      <Button variant="primary">Download backup</Button>
    </CardFoot>
  </Card>
);

export const GroupedRows: Story = () => (
  <MemoryRouter>
    <Card style={{ maxWidth: 560 }}>
      <ListRow
        to="/settings/access"
        icon={<LockIcon className="icon" />}
        title="Access & sign-in"
        description="Private · Dashboard sign-in off"
      />
      <ListRow
        to="/settings/backups"
        icon={<BackupIcon className="icon" />}
        title="Backups"
        description="Last backup 2 days ago"
      />
    </Card>
  </MemoryRouter>
);
