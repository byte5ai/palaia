import { LoadingState } from "../components/EmptyState";

/** What a lazily loaded screen shows while its code is on its way (issue
 * 406): grey lines after 300 ms, and "Loading this screen…" for screen
 * readers (and for tests that wait for it to go away). */
export function ScreenLoading() {
  return <LoadingState label="Loading this screen…" />;
}
