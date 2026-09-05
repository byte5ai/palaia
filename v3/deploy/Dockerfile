# palaia v3 hub image — multi-stage build.
#
# Stage 1 (web-build): builds the dashboard (v3/web) with Vite. Kept generic
# on purpose — the web app is still a skeleton (SPEC-109 lands it properly);
# this stage just builds whatever `npm run build` currently produces and
# copies the resulting `dist/` forward. Nothing here assumes a specific set
# of routes or assets.
#
# Stage 2 (hub-build): installs the `palaia-hub` Python package (uv, from
# the v3 workspace) into a virtualenv, without dev dependencies.
#
# Stage 3 (runtime): slim Debian base with the hub's venv, the built
# dashboard, and nginx as the single public entry point — nginx serves the
# static dashboard and reverse-proxies `/api/*` (and, from SPEC-105 onward,
# the MCP mount point) to the hub process on a loopback-only internal port.
# Runs as a non-root user. No embedding models are baked in: they download
# on first use into the PALAIA_HOME volume (see v3/deploy/README.md).

# ---------------------------------------------------------------------------
# Stage 1: web build
# ---------------------------------------------------------------------------
FROM node:22-slim AS web-build
WORKDIR /web
# .npmrc must ride along: it carries legacy-peer-deps=true (see its own
# comment), without which `npm ci` fails peer resolution inside this image
# while passing everywhere the file is present.
COPY v3/web/package.json v3/web/package-lock.json v3/web/.npmrc ./
RUN npm ci
COPY v3/web/ ./
# src/lib/skills.ts inlines the client skill sources from ../../../clients/
# (v3/clients/skills/*/SKILL.md, via vite's ?raw imports) — from /web that
# resolves to /clients, so the skills must ride along or the build fails
# with UNRESOLVED_IMPORT.
COPY v3/clients/ /clients/
RUN npm run build
# Result: /web/dist — copied into the runtime stage below. If a future SPEC
# changes the web app's build output directory, only this COPY needs to
# follow along with vite.config.ts's `build.outDir`.

# ---------------------------------------------------------------------------
# Stage 2: hub build (uv-managed venv, no dev dependencies)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS hub-build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/
WORKDIR /src
COPY v3/pyproject.toml v3/uv.lock ./
COPY v3/server/ ./server/
# The venv's console-script shebangs and the python symlink embed the path
# it was created at, so it must be built at the exact path the runtime
# stage will copy it to (venvs aren't relocatable) — hence UV_PROJECT_ENVIRONMENT
# rather than the workspace-default `.venv` under /src.
# --no-dev: runtime image never needs pytest/ruff/mypy/httpx.
ENV UV_PROJECT_ENVIRONMENT=/opt/palaia/venv
RUN uv sync --frozen --no-dev --no-editable --package palaia-hub
# python-zeroconf for the mDNS announcer (see mdns_announce.py in the
# runtime stage). Pure Python, no extra system deps — installed straight
# into the hub's venv but kept out of `palaia-hub`'s own dependency set
# since it is a deploy-only concern, not a hub feature.
RUN uv pip install --python "${UV_PROJECT_ENVIRONMENT}" "zeroconf>=0.140,<1"

# ---------------------------------------------------------------------------
# Stage 3: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# nginx: single public entry point (static dashboard + reverse proxy to the
# hub's internal port). curl: used by the HEALTHCHECK below. gettext-base:
# provides envsubst, used to render nginx.conf.template at container start.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx-light curl gettext-base \
    && rm -rf /var/lib/apt/lists/*

# A fixed uid/gid, never "whatever the base image hands out next" (issue
# #329): the app-store packages under stores/ bind-mount a host directory
# onto /data, and a bind mount keeps the host's ownership — so every package
# declares `user: "1000:1000"` and its SUBMIT.md says what to chown. 1000 is
# the conventional first non-system uid, the one Umbrel and Runtipi app
# packages commonly run as. Changing this number breaks every existing
# bind-mount install, so treat it as part of the image's contract.
RUN groupadd --system --gid 1000 palaia \
    && useradd --system --uid 1000 --gid palaia --create-home --home-dir /home/palaia \
       --shell /usr/sbin/nologin palaia

# Hub venv from stage 2 (already built at this exact path — see the
# UV_PROJECT_ENVIRONMENT note above).
COPY --from=hub-build /opt/palaia/venv /opt/palaia/venv
ENV PATH="/opt/palaia/venv/bin:${PATH}"

# Built dashboard, served by nginx.
COPY --from=web-build /web/dist /opt/palaia/dashboard

COPY v3/deploy/nginx.conf.template /opt/palaia/nginx.conf.template
COPY v3/deploy/entrypoint.sh /opt/palaia/entrypoint.sh
COPY v3/deploy/mdns_announce.py /opt/palaia/mdns_announce.py
RUN chmod +x /opt/palaia/entrypoint.sh \
    && mkdir -p /var/lib/nginx/body /tmp/nginx \
    && chown -R palaia:palaia /var/lib/nginx /tmp/nginx

# Data directory for PALAIA_HOME (mounted as a volume in compose/the
# one-liner). Owned by the non-root user up front so first run doesn't hit
# a permission error on a freshly created named volume (Docker copies the
# image's ownership into a new named volume). A *bind* mount keeps the
# host directory's ownership instead — that is what the fixed uid above
# and the `user:` line in every store package are for.
RUN mkdir -p /data && chown palaia:palaia /data

# SPEC-501: which release stream this exact image belongs to. Baked at
# build time by the release workflow (v3-release.yml passes
# `--build-arg PALAIA_CHANNEL=<stable|beta|edge>`, matching the GHCR tag(s)
# that build is pushed under) — never guessed at runtime, since a tag alone
# doesn't tell a running container which tag it was pulled by. A local
# `docker build` with no --build-arg stays "edge", same as config.py's own
# default for an un-imaged dev run.
ARG PALAIA_CHANNEL=edge

ENV PALAIA_HOME=/data \
    PALAIA_HOST=127.0.0.1 \
    PALAIA_PORT=8421 \
    PUBLIC_PORT=8420 \
    PALAIA_MDNS_ENABLED=1 \
    PALAIA_CHANNEL=${PALAIA_CHANNEL}

# Documented Watchtower-compatible opt-in label (SPEC-501 deliverable #4):
# https://containrrr.dev/watchtower/container-selection/ — an operator
# running Watchtower with `--label-enable` gets palaia included without any
# palaia-specific Watchtower configuration. palaia itself never runs
# Watchtower, and the dashboard never assumes it is running — this label
# only makes the *option* discoverable for operators who already use it.
LABEL com.centurylinklabs.watchtower.enable="true"

EXPOSE 8420
VOLUME ["/data"]

USER palaia
WORKDIR /home/palaia

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PUBLIC_PORT}/api/health" || exit 1

ENTRYPOINT ["/opt/palaia/entrypoint.sh"]
