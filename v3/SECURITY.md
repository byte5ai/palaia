# Security policy — palaia v3

This policy covers **palaia v3**, the hub that lives under `v3/` in this
repository. palaia v2 (the repository root) is on a maintenance branch with
its own, narrower promise — see the note at the end.

If you are reviewing the system rather than reporting a single issue, start
from [docs/security/external-review-brief.md](docs/security/external-review-brief.md).

## Supported versions

| Version | Supported | What that means |
|---|---|---|
| v3 `main` (pre-release) | Yes | Fixed on `main`; there is no released v3 yet, so there is nothing to backport to |
| v3 `stable` channel | Yes, once 3.0 ships | Security fixes land in the next patch release on the `stable` channel |
| v3 `beta` channel | Yes, once 3.0 ships | Fixed together with `stable`, usually first |
| v3 `edge` images | Best effort | Built from `main`; use it to verify a fix, not to run your memory on |
| v2 (repository root) | Critical only | Security, data loss and broken releases only, on the `v2-maintenance` branch |

Only the most recent minor release of v3 receives security fixes. There are
no long-term-support branches.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Two ways, either is fine:

1. **GitHub private vulnerability reporting** — the "Report a vulnerability"
   button under this repository's *Security* tab. This is the preferred
   route: it keeps the report, the discussion and the eventual advisory in
   one place.
2. **Email** — security@byte5.de. Say "palaia v3" in the subject so it is
   routed correctly.

Please include, as far as you have it:

- what an attacker can do, and what they need in order to do it (network
  position, an existing account, a connected client);
- the operating mode the hub was in (`locked`, `cloud` or `open`) and the
  version or commit;
- the smallest reproduction you have — a `curl`, a config snippet, a note
  that triggers it;
- anything you would like credited, and the name you would like credited by.

## What to expect from us

| Stage | Target |
|---|---|
| We acknowledge your report | Within 3 working days |
| We tell you whether we can reproduce it, and our initial severity | Within 7 working days |
| We ship a fix for a critical or high-severity issue | Within 30 days of confirmation |
| We ship a fix for anything else | In the next scheduled release |
| We publish an advisory | With the release that fixes it |

If a fix will take longer than the target, we will say so and why, rather
than go quiet. If we disagree that something is a vulnerability, we will say
that too, with our reasoning — and we would rather argue about it than
silently close it.

We ask for the usual courtesy in return: give us a chance to ship a fix
before publishing, and do not run tests against anyone else's hub.

## What is already known

Some things are deliberate trade-offs rather than bugs, and are documented
as such in [docs/security/threat-model.md](docs/security/threat-model.md) §8
— prompt injection being contained rather than prevented, the vault being
plain unencrypted files, `locked` mode trusting the local network. A report
that one of these is a bad trade-off is welcome and will get a real answer;
it is just not news.

## Scope

**In scope:** the hub daemon (`v3/server`), the dashboard (`v3/web`), the
packaged container and installer (`v3/deploy`), the add-on SDK (`v3/sdk`),
and the client bundles the hub generates.

**Out of scope:** vulnerabilities in third-party MCP servers a user chooses
to connect (report those to their maintainers — tell us too if palaia makes
them worse), findings that require an attacker to already have the user's
account on the host machine, and reports produced solely by a scanner with
no demonstrated impact.
