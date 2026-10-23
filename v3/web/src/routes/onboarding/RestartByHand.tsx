/** Where the hub cannot restart itself (no supervisor said it may): the
 * command, and the promise that the wizard notices when it is back. */
export function RestartByHand() {
  return (
    <div className="card">
      <div className="card__body stack stack--2">
        <p className="t-sm">
          This palaia can't restart itself here. Restart it where it runs, for
          example:
        </p>
        <div className="snippet">
          <code>docker restart palaia-hub</code>
        </div>
        <p className="t-sm t-muted">
          This page continues by itself once palaia is back.
        </p>
      </div>
    </div>
  );
}
