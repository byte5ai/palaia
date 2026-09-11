/** What a lazily loaded screen shows for the moment its code is still on
 * its way (issue 406) — text, not a spinner, so a slow connection reads
 * "loading", and tests can wait for it to go away. */
export function ScreenLoading() {
  return (
    <p className="t-sm t-muted" role="status">
      Loading this screen…
    </p>
  );
}
