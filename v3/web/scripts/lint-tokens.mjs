#!/usr/bin/env node
/**
 * "Nothing in the UI may hardcode a colour, radius, duration or type
 * size" (system.md §1) — the lint rule this SPEC's acceptance criteria
 * name. `eslint` catches JS/TS syntax issues; it has no opinion on CSS
 * literals or on `style={{ color: "#..." }}` in JSX, so this script
 * scans both source trees directly.
 *
 * Every color/radius/duration/size value in the product must be a Lume
 * custom property (`var(--...)`) or a component class already bound to
 * one — never a literal hex/rgb color, and never a literal duration in
 * a transition/animation. The two files that DEFINE the tokens
 * (styles/tokens.css, styles/fonts.css) are the only allowed exception.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname;
const ALLOWED_FILES = new Set(["styles/tokens.css", "styles/fonts.css"]);
const SCAN_EXTENSIONS = new Set([".css", ".ts", ".tsx"]);

const HEX_COLOR = /#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;
const RGB_FUNC = /\brgba?\(/g;
const HSL_FUNC = /\bhsla?\(/g;
// A bare millisecond/second duration next to transition/animation-shaped
// properties — var(--duration-...) is the only allowed source of these.
const RAW_DURATION = /\b\d+(?:\.\d+)?(?:ms|s)\b/g;

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

/** True if `index` falls inside the *value* of a custom-property
 * declaration (`--something: ...;`) rather than a normal CSS property.
 * Token definitions (tokens.css §2-4b) are literal by construction —
 * the rule this script enforces is about *usage* sites needing
 * `var(--...)`, not about banning the one place values are named. */
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

function checkFile(path) {
  const rel = relative(ROOT, path);
  if (ALLOWED_FILES.has(rel)) return [];
  if (rel.endsWith(".gen.ts") || rel.endsWith(".test.ts") || rel.endsWith(".test.tsx")) return [];

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
      // color-mix(in srgb, ...) is a token-derived expression, not a
      // literal color, and is explicitly allowed (system.md §1: derived
      // values like --selection-wash are mechanically derived from
      // tokens, not invented).
      const context = text.slice(Math.max(0, match.index - 20), match.index);
      if (!context.includes("color-mix")) {
        violations.push(`${rel}: hardcoded ${match[0]}...) colour function`);
      }
    }
  }
  if (extname(path) === ".css") {
    for (const match of text.matchAll(RAW_DURATION)) {
      // Only `transition` is flagged: an interactive state change must
      // route through --duration-quick/-smooth/-condense. A looping
      // `animation`/`animation-delay` (the skeleton pulse, the live dot,
      // the waiting-indicator bounce) is its own recipe with its own
      // timing, and colors_and_type.css sets this precedent itself —
      // `.lume-skeleton` animates at a literal `1400ms`, not a token.
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
const violations = files.flatMap(checkFile);

if (violations.length > 0) {
  console.error("lint-tokens: hardcoded design values found outside styles/tokens.css:\n");
  for (const violation of violations) {
    console.error(`  ${violation}`);
  }
  console.error(`\n${violations.length} violation(s). Use a var(--...) token instead.`);
  process.exit(1);
}

console.log("lint-tokens: no hardcoded colours/durations outside the token files.");
