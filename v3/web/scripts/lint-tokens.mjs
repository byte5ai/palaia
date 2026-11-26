#!/usr/bin/env node
/**
 * Design-token lint (v3/docs/design/system.md §1): every colour, type size,
 * radius and transition duration in the dashboard comes from a custom
 * property, every layout switch happens at a breakpoint of the system, and
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
 *   4. No literal `font-size`, `line-height` or `border-radius` in px or rem
 *      (a type style or a radius token instead; `0`, `50%` and `em` values
 *      relative to the surrounding text are not design values).
 *   5. Every `@media` width is a breakpoint from v3/design/tokens.json.
 *   6. No inline `style={{…}}` in a screen or a component. A look belongs to
 *      a class of the system; only a value computed at run time (a progress
 *      width, a popover's position, a skeleton's size) is set inline, in the
 *      files listed in INLINE_STYLE_FILES.
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
const LITERAL_SCALE = /\b(font-size|line-height|border-radius)\s*:\s*([^;}]*)/g;
const LENGTH = /(?<![\w.-])(\d*\.?\d+)(px|rem)\b/g;
const MEDIA_WIDTH = /\((min|max)-width:\s*(\d+)px\)/g;
const INLINE_STYLE = /\bstyle=\{\{/g;
const INLINE_STYLE_FILES = new Set([
  "components/Stepper.tsx",
  "components/Skeleton.tsx",
  "shell/NotificationBell.tsx",
]);

const TOKENS = JSON.parse(
  readFileSync(new URL("../../design/tokens.json", import.meta.url), "utf-8"),
);
/** `max-width` and `min-width` values a media query may use. */
const BREAKPOINT_WIDTHS = {
  max: new Set(TOKENS.breakpoints.filter((b) => b.max).map((b) => b.max)),
  min: new Set(TOKENS.breakpoints.filter((b) => b.min).map((b) => b.min)),
};
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

/** The text with comments blanked out (same length, so indexes still line
 * up): "issue #570" in a comment is not a colour. Strings are left alone —
 * a colour in a string is exactly what this lint is for. */
function withoutComments(text, isCss) {
  const blank = (match) => match.replace(/[^\n]/g, " ");
  const block = text.replace(/\/\*[\s\S]*?\*\//g, blank);
  return isCss ? block : block.replace(/(^|[^:"'`\\])\/\/[^\n]*/g, (match, lead) => lead + blank(match.slice(lead.length)));
}

function isSkipped(rel) {
  return rel.endsWith(".gen.ts") || rel.endsWith(".test.ts") || rel.endsWith(".test.tsx");
}

function checkLiterals(path) {
  const rel = relative(ROOT, path);
  if (ALLOWED_FILES.has(rel) || isSkipped(rel)) return [];

  const isCss = extname(path) === ".css";
  const text = withoutComments(readFileSync(path, "utf-8"), isCss);
  const violations = [];

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
  if (!isCss && !rel.endsWith(".stories.tsx") && !INLINE_STYLE_FILES.has(rel)) {
    for (const _ of text.matchAll(INLINE_STYLE)) {
      violations.push(`${rel}: inline style — use a class from components.css`);
    }
  }
  if (isCss) {
    for (const match of text.matchAll(LITERAL_SCALE)) {
      if (isInsideCustomPropertyValue(text, match.index)) continue;
      for (const length of match[2].matchAll(LENGTH)) {
        if (Number(length[1]) === 0) continue;
        violations.push(`${rel}: literal ${match[1]} ${length[0]} outside the type and radius tokens`);
      }
    }
    for (const match of text.matchAll(MEDIA_WIDTH)) {
      if (!BREAKPOINT_WIDTHS[match[1]].has(Number(match[2]))) {
        violations.push(`${rel}: @media (${match[1]}-width: ${match[2]}px) is not a breakpoint of the system`);
      }
    }
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
  const text = withoutComments(readFileSync(path, "utf-8"), extname(path) === ".css");
  for (const match of text.matchAll(VAR_USE)) {
    if (!defined.has(match[1])) violations.push(`${rel}: var(${match[1]}) is not defined anywhere`);
  }
}

if (violations.length > 0) {
  console.error("lint-tokens: design values that bypass the tokens:\n");
  for (const violation of violations) {
    console.error(`  ${violation}`);
  }
  console.error(
    `\n${violations.length} violation(s). Use a var(--...) token from tokens.css, or add the value to v3/design/tokens.json.`,
  );
  process.exit(1);
}

console.log(
  "lint-tokens: every colour, type size, radius, duration, breakpoint and custom property resolves to a token.",
);
