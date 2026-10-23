/**
 * What the router shows when a URL matches nothing, or a screen throws
 * while rendering (issue 379) — inside the shell when the shell itself is
 * fine, in palaia's own words, with a way on.
 */
import { isRouteErrorResponse, useRouteError } from "react-router-dom";

import { Button, Disclosure, EmptyState, LinkButton } from "../components";
import { ErrorIcon, HomeIcon } from "../shell/icons";

export function NotFound() {
  return (
    <EmptyState
      mark={<HomeIcon className="icon icon--xl" />}
      title="That page doesn't exist"
      actions={
        <LinkButton variant="primary" to="/">
          Go to Overview
        </LinkButton>
      }
    >
      The address may have a typo, or the page moved.
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
    <div className="stack">
      <EmptyState
        mark={<ErrorIcon className="icon icon--xl" />}
        title="Something went wrong on this page"
        actions={
          <>
            <Button variant="primary" onClick={() => window.location.reload()}>
              Reload
            </Button>
            <LinkButton to="/">Go to Overview</LinkButton>
          </>
        }
      >
        Reload to try again.
      </EmptyState>
      {detail ? (
        <div className="narrow" style={{ margin: "0 auto" }}>
          <Disclosure summary="Show details">
            <p className="t-mono">{detail}</p>
          </Disclosure>
        </div>
      ) : null}
    </div>
  );
}
