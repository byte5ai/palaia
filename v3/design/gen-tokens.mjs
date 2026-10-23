#!/usr/bin/env node
/**
 * palaia design tokens: one source, two generated stylesheets.
 *
 * `tokens.json` (this folder) is the only place a colour, type step, space,
 * radius, shadow or layout size is written down. This script turns it into
 *
 *   - `v3/web/src/styles/tokens.css`         the dashboard's custom properties
 *   - `v3/site/docs/src/styles/palaia-tokens.css`  Starlight's colour and font
 *                                             variables, mapped onto the same values
 *
 * Both files are committed (the dashboard's Docker build copies `v3/web/` only,
 * so nothing may be generated at build time). Run it after editing
 * `tokens.json`:
 *
 *   node v3/design/gen-tokens.mjs           write both files
 *   node v3/design/gen-tokens.mjs --check   exit 1 if either file is stale
 *
 * The web and docs test suites run the `--check` form, so a hand edit to a
 * generated file, or a `tokens.json` change without regenerating, fails CI.
 *
 * Theme switching (both outputs): light is the default; dark applies when the
 * system asks for it unless the page pins light with `data-theme="light"`, and
 * always under `data-theme="dark"`. The docs site follows Starlight's own
 * convention instead, where bare `:root` is dark and `[data-theme='light']` is
 * light.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const V3 = join(HERE, "..");
const SOURCE = join(HERE, "tokens.json");
const WEB_OUT = join(V3, "web/src/styles/tokens.css");
const DOCS_OUT = join(V3, "site/docs/src/styles/palaia-tokens.css");

const HEADER = (target) => `/* =============================================================
   GENERATED FILE. Do not edit by hand.
   Source: v3/design/tokens.json · generator: v3/design/gen-tokens.mjs
   Regenerate with \`node v3/design/gen-tokens.mjs\`; CI fails when this
   file and tokens.json disagree.
   ${target}
   ============================================================= */
`;

function load() {
  return JSON.parse(readFileSync(SOURCE, "utf-8"));
}

function colorValue(tokens, name, theme) {
  const token = tokens.color.tokens.find((t) => t.name === name);
  if (!token) throw new Error(`tokens.json has no colour "${name}"`);
  return token.value[theme];
}

function themed(value, theme) {
  return typeof value === "object" && value !== null ? value[theme] : value;
}

function block(selector, lines, indent = "") {
  return `${indent}${selector} {\n${lines.map((l) => `${indent}  ${l}`).join("\n")}\n${indent}}\n`;
}

/** Colour and shadow declarations for one theme. */
function themeLines(tokens, theme) {
  const lines = [`color-scheme: ${theme};`];
  for (const token of tokens.color.tokens) {
    lines.push(`--${token.name}: ${token.value[theme]};`);
  }
  for (const token of tokens.shadow.tokens) {
    lines.push(`--${token.name}: ${themed(token.value, theme)};`);
  }
  return lines;
}

/** Everything that does not change with the theme. */
function staticLines(tokens) {
  const lines = [];
  const families = tokens.type.families;
  lines.push(`--font-sans: ${families.sans};`);
  lines.push(`--font-display: ${families.display};`);
  lines.push(`--font-mono: ${families.mono};`);
  for (const group of tokens.type.groups) {
    for (const style of group.styles) {
      lines.push(
        `--type-${style.name}-size: ${style.fontSize}; ` +
          `--type-${style.name}-lh: ${style.lineHeight}; ` +
          `--type-${style.name}-weight: ${style.fontWeight};`,
      );
    }
  }
  for (const token of tokens.spacing.tokens) lines.push(`--${token.name}: ${token.value};`);
  for (const token of tokens.radius.tokens) lines.push(`--${token.name}: ${token.value};`);
  for (const token of tokens.size.tokens) lines.push(`--${token.name}: ${token.value};`);
  return lines;
}

export function renderWebCss(tokens) {
  const light = themeLines(tokens, "light");
  const dark = themeLines(tokens, "dark");
  return [
    HEADER("Target: the dashboard (v3/web). Names match tokens.json one to one."),
    block(":root", [...staticLines(tokens), ...light]),
    "@media (prefers-color-scheme: dark) {\n" +
      block(':root:not([data-theme="light"])', dark, "  ") +
      "}\n",
    block(':root[data-theme="dark"]', dark),
  ].join("\n");
}

/**
 * Starlight's palette, mapped once onto the shared tokens. Starlight reads its
 * grey scale from "most contrast" (white, gray-1) to "least" (gray-6, black):
 * in dark mode white is the text colour and black the page; light mode flips
 * both ends. Accent: `accent` colours links and buttons in light mode,
 * `accent-high` in dark mode, `accent-low` the tinted backgrounds.
 */
function starlightLines(tokens, theme) {
  const c = (name) => colorValue(tokens, name, theme);
  const lines = [
    `--sl-color-white: ${c("text")};`,
    `--sl-color-gray-1: ${c("text")};`,
    `--sl-color-gray-2: ${c("text")};`,
    `--sl-color-gray-3: ${c("text-2")};`,
    `--sl-color-gray-4: ${c("text-3")};`,
    `--sl-color-gray-5: ${c("border")};`,
  ];
  if (theme === "dark") {
    lines.push(
      `--sl-color-gray-6: ${c("surface")};`,
      `--sl-color-black: ${c("canvas")};`,
      `--sl-color-accent-low: ${c("info-bg")};`,
      `--sl-color-accent: ${c("brand")};`,
      `--sl-color-accent-high: ${c("action")};`,
    );
  } else {
    lines.push(
      `--sl-color-gray-6: ${c("surface-muted")};`,
      `--sl-color-gray-7: ${c("canvas")};`,
      `--sl-color-black: ${c("surface")};`,
      `--sl-color-accent-low: ${c("info-bg")};`,
      `--sl-color-accent: ${c("action")};`,
      `--sl-color-accent-high: ${c("action-hover")};`,
    );
  }
  return lines;
}

export function renderDocsCss(tokens) {
  const families = tokens.type.families;
  return [
    HEADER("Target: the docs site (Starlight). Bare :root is dark, [data-theme='light'] light."),
    block(":root", [
      `--sl-font: ${families.sans};`,
      `--sl-font-mono: ${families.mono};`,
      `--palaia-font-display: ${families.display};`,
      ...starlightLines(tokens, "dark"),
    ]),
    block(":root[data-theme='light']", starlightLines(tokens, "light")),
  ].join("\n");
}

const OUTPUTS = [
  [WEB_OUT, renderWebCss],
  [DOCS_OUT, renderDocsCss],
];

function main() {
  const check = process.argv.includes("--check");
  const tokens = load();
  const stale = [];
  for (const [path, render] of OUTPUTS) {
    const wanted = render(tokens);
    let current = null;
    try {
      current = readFileSync(path, "utf-8");
    } catch {
      current = null;
    }
    if (current === wanted) continue;
    if (check) {
      stale.push(relative(V3, path));
    } else {
      writeFileSync(path, wanted);
      console.log(`wrote ${relative(V3, path)}`);
    }
  }
  if (check && stale.length > 0) {
    console.error(
      `gen-tokens: out of date with v3/design/tokens.json: ${stale.join(", ")}.\n` +
        "Run `node v3/design/gen-tokens.mjs` and commit the result.",
    );
    process.exit(1);
  }
  if (check) console.log("gen-tokens: generated token files match tokens.json.");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
