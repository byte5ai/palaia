// The single-source extraction this SPEC's deliverable #2 requires: bundle
// v3/web/src/lib/clients.ts and skills.ts — the real dashboard connect-page
// source, not a copy of it — and hand back their exported data so the
// generator can render docs pages from it. No client name, command, prompt
// or skill description is retyped anywhere in this directory; every one of
// those strings is read out of the files the dashboard itself ships.
import { build } from "esbuild";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// scripts/lib -> scripts -> docs -> site -> v3 -> web/src/lib
export const WEB_LIB = path.resolve(__dirname, "../../../../web/src/lib");
const CLIENTS_TS = path.join(WEB_LIB, "clients.ts");
const SKILLS_TS = path.join(WEB_LIB, "skills.ts");

/** Vite's `?raw` string-import convention, used by skills.ts — esbuild has
 * no built-in equivalent, so this plugin reads the target file itself and
 * exports its text, exactly what Vite does at the dashboard's own build. */
const rawTextPlugin = {
  name: "raw-text",
  setup(b) {
    b.onResolve({ filter: /\?raw$/ }, (args) => ({
      path: path.resolve(args.resolveDir, args.path.replace(/\?raw$/, "")),
      namespace: "raw-text",
    }));
    b.onLoad({ filter: /.*/, namespace: "raw-text" }, (args) => ({
      contents: `export default ${JSON.stringify(readFileSync(args.path, "utf8"))};`,
      loader: "js",
    }));
  },
};

/** clients.ts imports React icon components purely to decorate the
 * dashboard's UI — irrelevant to the docs site, which renders no icons.
 * Stubbed so bundling clients.ts needs no React runtime at all. */
const stubIconsPlugin = {
  name: "stub-icons",
  setup(b) {
    b.onResolve({ filter: /shell\/icons$/ }, () => ({
      path: "palaia-stub-icons",
      namespace: "stub-icons",
    }));
    b.onLoad({ filter: /.*/, namespace: "stub-icons" }, () => ({
      contents: ["ClientsIcon", "ExplorerIcon", "LinkIcon", "SparkleIcon", "ToolsIcon"]
        .map((name) => `export const ${name} = ${JSON.stringify(name)};`)
        .join("\n"),
      loader: "js",
    }));
  },
};

/**
 * Bundle clients.ts + skills.ts to one in-memory ESM module, execute it in
 * a throwaway temp file, and return the exports the generator needs.
 */
export async function loadCatalog() {
  const entry = [
    `export * as clientsModule from ${JSON.stringify(CLIENTS_TS)};`,
    `export * as skillsModule from ${JSON.stringify(SKILLS_TS)};`,
  ].join("\n");

  const result = await build({
    stdin: { contents: entry, resolveDir: WEB_LIB, loader: "ts" },
    bundle: true,
    format: "esm",
    platform: "node",
    write: false,
    plugins: [rawTextPlugin, stubIconsPlugin],
    logLevel: "silent",
  });

  const tmpDir = mkdtempSync(path.join(os.tmpdir(), "palaia-docs-extract-"));
  const tmpFile = path.join(tmpDir, "catalog.mjs");
  writeFileSync(tmpFile, result.outputFiles[0].text, "utf8");
  try {
    const mod = await import(pathToFileURL(tmpFile).href);
    return {
      clients: mod.clientsModule.CLIENTS,
      skills: mod.skillsModule.SKILLS,
      skillSupportFor: mod.skillsModule.skillSupportFor,
      frontmatterValue: mod.skillsModule.frontmatterValue,
    };
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}
