/**
 * What the router shows when a URL matches nothing, or a screen throws
 * while rendering (issue 379).
 *
 * The hub serves `index.html` for every dashboard path, so a typo like
 * `/explorer/typo` reaches the router — which, with no `errorElement`,
 * showed React Router's own "Unexpected Application Error!" page. Both
 * cases now get a page in the dashboard's own words, inside the shell
 * when the shell itself is fine, with a way back.
 */
import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";

import { EmptyState } from "../components";
import { HomeIcon } from "../shell/icons";

export function NotFound() {
  return (
    <EmptyState mark={<HomeIcon className="icon--lg" />} title="That page doesn't exist.">
      The address may have a typo, or the page moved.{" "}
      <Link to="/">Back to Home</Link>.
    </EmptyState>
  );
}

export function RouteError() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) return <NotFound />;

  const detail =
    error instanceof Error
      ? error.message
      : isRouteErrorResponse(error)
        ? `${error.status} ${error.statusText}`.trim()
        : "";

  return (
    <EmptyState mark={<HomeIcon className="icon--lg" />} title="This screen ran into a problem.">
      Reloading the page usually fixes it; if it keeps happening, the hub&rsquo;s logs will
      say why. <Link to="/">Back to Home</Link>.
      {detail ? (
        <>
          <br />
          <code className="t-xs t-subtle">{detail}</code>
        </>
      ) : null}
    </EmptyState>
  );
}
