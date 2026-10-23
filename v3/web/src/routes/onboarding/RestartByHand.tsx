import { Callout } from "../../components/Callout";
import { RESTART_COMMAND } from "../../components/RestartHub";

/** Where the hub cannot restart itself (no supervisor said it may): the
 * command, and the promise that the wizard notices when it is back. */
export function RestartByHand() {
  return (
    <Callout tone="info" title="Restart palaia on its server">
      <p>
        This palaia can't restart itself here. Run <code>{RESTART_COMMAND}</code> where it
        runs.
      </p>
      <p>This page continues by itself once palaia is back.</p>
    </Callout>
  );
}
