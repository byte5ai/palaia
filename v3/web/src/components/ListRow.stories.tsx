import type { Story } from "@ladle/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";

import { ClientsIcon, SparkleIcon } from "../shell/icons";
import { Button } from "./Button";
import { Card } from "./Card";
import { Segmented, Switch } from "./Field";
import { ListRow } from "./ListRow";
import { StatusPill } from "./StatusPill";

export default {
  title: "Data display / ListRow",
};

export const Items: Story = () => (
  <MemoryRouter>
    <Card style={{ maxWidth: 640 }}>
      <ListRow
        icon={<SparkleIcon className="icon" />}
        title="Claude Code CLI"
        description="Last request 2 min ago"
        trailing={<StatusPill tone="ok">Connected</StatusPill>}
      />
      <ListRow
        icon={<ClientsIcon className="icon" />}
        title="Claude Desktop"
        description="Access key created, no request yet"
        trailing={<StatusPill tone="info">Waiting for first use</StatusPill>}
      />
      <ListRow
        icon={<ClientsIcon className="icon" />}
        title="claude.ai"
        description="Connects from the internet"
        trailing={
          <>
            <StatusPill tone="warn">Needs Cloud mode</StatusPill>
            <Button size="sm">Set up</Button>
          </>
        }
      />
      <ListRow to="/apps" title="All AI apps" description="1 of 9 connected" />
    </Card>
  </MemoryRouter>
);

export const SettingRows: Story = () => {
  const [keys, setKeys] = useState(true);
  const [theme, setTheme] = useState<"system" | "light" | "dark">("system");
  return (
    <Card style={{ maxWidth: 640 }}>
      <ListRow
        setting
        title="AI apps need an access key"
        description="Each app connects with its own key, which you can revoke."
        labelId="story-keys"
        trailing={<Switch checked={keys} onChange={setKeys} labelledBy="story-keys" />}
      />
      <ListRow
        setting
        title="Appearance"
        description="Light or dark, or follow this device."
        trailing={
          <Segmented
            ariaLabel="Appearance"
            value={theme}
            onChange={setTheme}
            options={[
              { value: "system", label: "System" },
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
            ]}
          />
        }
      />
    </Card>
  );
};
