/**
 * Dashboard settings (SPEC-204 deliverable #4): a plain-language read-out of
 * how the owner signs in. Sign-in itself is configured in `config.yaml` (an
 * operator action, not a dashboard flow) — this section exists so the
 * operator can confirm what's active without reading that file, in copy
 * that passes the jargon rule: "Sign in with GitHub", never "OIDC".
 */
import { useEffect, useState } from "react";

import { Badge, Card, CardBody, CardHead } from "../components";
import type { SignInInfo } from "../lib/api/client";
import { api } from "../lib/api/client";

type LoadState = "loading" | "loaded" | "error";

function signInSummary(signIn: SignInInfo): { label: string; detail: string } {
  if (signIn.method === "idp" && signIn.provider_name) {
    return {
      label: `Sign in with ${signIn.provider_name}`,
      detail:
        "The owner account signs in through this provider. Set in config.yaml by the hub's operator.",
    };
  }
  if (signIn.method === "password") {
    return {
      label: "Sign in with a password",
      detail:
        "The owner account signs in with a local username and password, set with " +
        "`palaia-hub oauth set-password`.",
    };
  }
  return {
    label: "No sign-in configured",
    detail: "This hub is not set up to authenticate remote connections yet.",
  };
}

export function Settings() {
  const [state, setState] = useState<LoadState>("loading");
  const [signIn, setSignIn] = useState<SignInInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .info()
      .then((info) => {
        if (cancelled) return;
        const raw = (info as { sign_in?: SignInInfo }).sign_in;
        setSignIn(raw ?? null);
        setState("loaded");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <Card>
        <CardHead title="Sign-in">
          {state === "loaded" && signIn ? (
            <Badge variant={signIn.method === "none" ? "warn" : "ok"}>
              {signIn.method === "none" ? "not set up" : "on"}
            </Badge>
          ) : null}
        </CardHead>
        <CardBody>
          {state === "loading" ? <p className="t-sm t-muted">Loading…</p> : null}
          {state === "error" ? (
            <p className="t-sm t-muted">Could not load the hub's sign-in settings.</p>
          ) : null}
          {state === "loaded" && signIn ? (
            <div className="stack" style={{ gap: 4 }}>
              <p className="card__subject">{signInSummary(signIn).label}</p>
              <p className="t-sm t-muted">{signInSummary(signIn).detail}</p>
            </div>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
