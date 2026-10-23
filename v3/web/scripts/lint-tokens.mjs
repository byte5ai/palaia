#!/usr/bin/env node
/**
 * Design-token lint (v3/docs/design/system.md §1): every colour and every
 * transition duration in the dashboard comes from a custom property, and
 * every custom property the code reads exists.
 *
 * eslint has no opinion on CSS literals or on `style={{ color: "#..." }}`
 * in JSX, so this script scans the source tree directly:
 *
 *   1. No literal hex/rgb()/hsl() colour outside a custom-property
 *      definition (`--name: …;`). tokens.css is generated from
 *      v3/design/tokens.json and is the only file that defines palette
 *      colours; components.css names a handful of component constants.
 *   2. No literal duration in a `transition:` outside var(--duration-*).
 *   3. Every `var(--name)` used in a .css/.ts/.tsx file is defined in one of
 *      the stylesheets — so a token that was renamed or removed fails here
 *      instead of silently rendering nothing.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname;
const ALLOWED_FILES = new Set(["styles/tokens.css", "styles/fonts.css"]);
const SCAN_EXTENSIONS = new Set([".css", ".ts", ".tsx"]);

const HEX_COLOR = /#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;
const RGB_FUNC = /\brgba?\(/g;
const HSL_FUNC = /\bhsla?\(/g;
const RAW_DURATION = /\b\d+(?:\.\d+)?(?:ms|s)\b/g;
const VAR_USE = /var\(\s*(--[a-zA-Z0-9_-]+)/g;
const VAR_DEF = /(?:^|[{;\s])(--[a-zA-Z0-9_-]+)\s*:/g;

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      walk(full, out);
    } else if (SCAN_EXTENSIONS.has(extname(entry))) {
      out.push(full);
    }
  }
  return out;
}

/** True if `index` falls inside the value of a custom-property declaration
 * (`--something: ...;`) rather than a normal CSS property. */
function isInsideCustomPropertyValue(text, index) {
  const declStart = Math.max(
    text.lastIndexOf("{", index),
    text.lastIndexOf(";", index),
    text.lastIndexOf("}", index),
  );
  const colon = text.indexOf(":", declStart);
  if (colon === -1 || colon > index) return false;
  const propertyName = text.slice(declStart + 1, colon).trim();
  return propertyName.startsWith("--");
}

function isSkipped(rel) {
  return rel.endsWith(".gen.ts") || rel.endsWith(".test.ts") || rel.endsWith(".test.tsx");
}

function checkLiterals(path) {
  const rel = relative(ROOT, path);
  if (ALLOWED_FILES.has(rel) || isSkipped(rel)) return [];

  const text = readFileSync(path, "utf-8");
  const violations = [];
  const isCss = extname(path) === ".css";

  for (const match of text.matchAll(HEX_COLOR)) {
    if (isCss && isInsideCustomPropertyValue(text, match.index)) continue;
    violations.push(`${rel}: hardcoded hex colour ${match[0]}`);
  }
  for (const pattern of [RGB_FUNC, HSL_FUNC]) {
    for (const match of text.matchAll(pattern)) {
      if (isCss && isInsideCustomPropertyValue(text, match.index)) continue;
      const context = text.slice(Math.max(0, match.index - 20), match.index);
      if (!context.includes("color-mix")) {
        violations.push(`${rel}: hardcoded ${match[0]}...) colour function`);
      }
    }
  }
  if (isCss) {
    for (const match of text.matchAll(RAW_DURATION)) {
      // Only `transition` is checked: a state change routes through
      // --duration-quick/-smooth. Looping animations (skeleton pulse, the
      // live dot, the spinner) carry their own timing.
      const lineStart = text.lastIndexOf("\n", match.index);
      const line = text.slice(lineStart, text.indexOf("\n", match.index));
      if (/\btransition\s*:/.test(line) && !line.includes("var(--duration")) {
        violations.push(`${rel}: literal duration ${match[0]} outside var(--duration-*)`);
      }
    }
  }
  return violations;
}

const files = walk(ROOT);
const violations = files.flatMap(checkLiterals);

const defined = new Set();
for (const path of files.filter((file) => extname(file) === ".css")) {
  for (const match of readFileSync(path, "utf-8").matchAll(VAR_DEF)) defined.add(match[1]);
}
for (const path of files) {
  const rel = relative(ROOT, path);
  if (isSkipped(rel)) continue;
  const text = readFileSync(path, "utf-8");
  for (const match of text.matchAll(VAR_USE)) {
    if (!defined.has(match[1])) violations.push(`${rel}: var(${match[1]}) is not defined anywhere`);
  }
}

if (violations.length > 0) {
  console.error("lint-tokens: design values that bypass the tokens:\n");
  for (const violation of violations) {
    console.error(`  ${violation}`);
  }
  console.error(`\n${violations.length} violation(s). Use a var(--...) token from tokens.css.`);
  process.exit(1);
}

console.log("lint-tokens: every colour, duration and custom property resolves to a token.");
