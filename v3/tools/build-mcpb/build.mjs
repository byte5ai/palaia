#!/usr/bin/env node
/**
 * Builds and signs `dist/palaia.mcpb` — SPEC-306 deliverable #2, "packed
 * via the official `mcpb` tooling in CI".
 *
 * Steps, all through the official `@anthropic-ai/mcpb` CLI (never a
 * hand-rolled zip/signature — see `SIGNING.md` for why that matters here):
 *
 *   1. Stage `manifest.template.json` (renamed to `manifest.json`, with
 *      its `version` field set from this package's own `--set-version`
 *      argument or the `PALAIA_VERSION` env var) alongside `proxy/` and
 *      `icon.png` in a throwaway directory — never in this directory
 *      itself, so a build never leaves a stray `manifest.json` next to
 *      the template that generates it.
 *   2. `mcpb validate` the staged manifest (fails the build loudly on any
 *      schema violation — this is what makes the CI job's "packed bundle
 *      validates against the MCPB manifest schema" acceptance criterion
 *      true rather than assumed).
 *   3. `mcpb pack` the staged directory into `dist/palaia.mcpb`.
 *   4. `mcpb sign` it. Self-signed by default (`--self-signed`, generating
 *      `dist/cert.pem`/`dist/key.pem` on first run and reusing them on
 *      every later run — the certificate's *identity* stays constant
 *      across builds, only the signature over each new artifact
 *      changes); a real CA-issued cert is used instead when
 *      `PALAIA_MCPB_CERT`/`PALAIA_MCPB_KEY` name existing PEM files (a
 *      production release pipeline's job, not this repo's CI secrets
 *      today — see SIGNING.md).
 *
 * `palaia_hub.mcpb.builder` (the server-side personalizer) runs the exact
 * same pack+sign steps against a per-download manifest, reusing this
 * directory's `proxy/`, `icon.png` and the persistent cert/key pair — see
 * that module's docstring.
 */
import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const run = promisify(execFile);
const HERE = path.dirname(fileURLToPath(import.meta.url));

function mcpbBin() {
  // Prefer a locally-installed devDependency (`npm ci` in this directory);
  // fall back to whatever `mcpb` is on PATH (a global install) so this
  // script also works for a developer who installed the CLI globally per
  // the upstream quickstart.
  const local = path.join(HERE, "node_modules", ".bin", process.platform === "win32" ? "mcpb.cmd" : "mcpb");
  return local;
}

async function mcpb(args, options = {}) {
  const bin = mcpbBin();
  const hasLocal = await fs
    .access(bin)
    .then(() => true)
    .catch(() => false);
  const command = hasLocal ? bin : "mcpb";
  const { stdout, stderr } = await run(command, args, { cwd: HERE, ...options });
  if (stdout.trim()) process.stdout.write(stdout);
  if (stderr.trim()) process.stderr.write(stderr);
}

async function stageBundle(version) {
  const stagingDir = await fs.mkdtemp(path.join(os.tmpdir(), "palaia-mcpb-"));
  const template = JSON.parse(await fs.readFile(path.join(HERE, "manifest.template.json"), "utf8"));
  template.version = version;
  await fs.writeFile(path.join(stagingDir, "manifest.json"), `${JSON.stringify(template, null, 2)}\n`);
  await fs.mkdir(path.join(stagingDir, "proxy"), { recursive: true });
  await fs.copyFile(
    path.join(HERE, "proxy", "palaia-proxy.mjs"),
    path.join(stagingDir, "proxy", "palaia-proxy.mjs"),
  );
  await fs.copyFile(path.join(HERE, "icon.png"), path.join(stagingDir, "icon.png"));
  return stagingDir;
}

export async function buildBundle({ version, outFile, sign = true } = {}) {
  const stagingDir = await stageBundle(version || process.env.PALAIA_VERSION || "0.0.0-dev");
  try {
    await mcpb(["validate", path.join(stagingDir, "manifest.json")]);
    const dist = path.dirname(outFile);
    await fs.mkdir(dist, { recursive: true });
    await mcpb(["pack", stagingDir, outFile]);
    if (sign) await signBundle(outFile, dist);
    return outFile;
  } finally {
    await fs.rm(stagingDir, { recursive: true, force: true });
  }
}

export async function signBundle(mcpbFile, certDir) {
  const cert = process.env.PALAIA_MCPB_CERT || path.join(certDir, "cert.pem");
  const key = process.env.PALAIA_MCPB_KEY || path.join(certDir, "key.pem");
  const haveCert = await fs
    .access(cert)
    .then(() => true)
    .catch(() => false);
  const args = ["sign", "--cert", cert, "--key", key];
  if (!haveCert) args.push("--self-signed");
  await mcpb([...args, mcpbFile]);
}

const isMain = fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || "");
if (isMain) {
  const outFile = path.join(HERE, "dist", "palaia.mcpb");
  buildBundle({ outFile })
    .then(() => {
      console.log(`built and signed ${outFile}`);
    })
    .catch((err) => {
      console.error(err.stack || err.message);
      process.exit(1);
    });
}
