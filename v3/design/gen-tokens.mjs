#!/usr/bin/env node
/**
 * palaia design tokens: one source, two generated stylesheets and the
 * token tables of the specification.
 *
 * `tokens.json` (this folder) is the only place a colour, type step, space,
 * radius, shadow, size, duration or breakpoint is written down. This script
 * turns it into
 *
 *   - `v3/web/src/styles/tokens.css`         the dashboard's custom properties
 *   - `v3/site/docs/src/styles/palaia-tokens.css`  Starlight's colour and font
 *                                             variables, mapped onto the same values
 *   - the tables between `<!-- generated:… -->` markers in
 *     `v3/docs/design/system.md`, so the specification states what ships
 *
 * It also measures every colour pair `tokens.json` lists under `contrast`,
 * in both themes, and fails when one is below its minimum (WCAG 2.2: 4.5:1
 * for text, 3:1 for the edge of a control and the focus ring).
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
const SPEC_OUT = join(V3, "docs/design/system.md");

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
  for (const token of tokens.motion.tokens) lines.push(`--${token.name}: ${token.value};`);
  return lines;
}

/** The sizes that differ on a phone, as one media block. */
function phoneBlock(tokens) {
  const phone = tokens.breakpoints.find((b) => b.name === "phone");
  const lines = tokens.size.tokens
    .filter((token) => token.phone)
    .map((token) => `--${token.name}: ${token.phone};`);
  return `@media (max-width: ${phone.max}px) {\n${block(":root", lines, "  ")}}\n`;
}

export function renderWebCss(tokens) {
  const light = themeLines(tokens, "light");
  const dark = themeLines(tokens, "dark");
  return [
    HEADER("Target: the dashboard (v3/web). Names match tokens.json one to one."),
    block(":root", [...staticLines(tokens), ...light]),
    phoneBlock(tokens),
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

// ------------------------------------------------------------- contrast

function luminance(hex) {
  const channel = (offset) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function contrastRatio(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** Every declared pair, measured in both themes. */
export function contrastRows(tokens) {
  return tokens.contrast.map((pair) => ({
    ...pair,
    light: contrastRatio(colorValue(tokens, pair.fg, "light"), colorValue(tokens, pair.bg, "light")),
    dark: contrastRatio(colorValue(tokens, pair.fg, "dark"), colorValue(tokens, pair.bg, "dark")),
  }));
}

function contrastFailures(tokens) {
  return contrastRows(tokens).flatMap((row) =>
    ["light", "dark"]
      .filter((theme) => row[theme] < row.min)
      .map(
        (theme) =>
          `${row.fg} on ${row.bg} (${theme}): ${row[theme].toFixed(2)}:1, needs ${row.min}:1 — ${row.use}`,
      ),
  );
}

// --------------------------------------------- tables of the specification

function table(head, rows) {
  const line = (cells) => `| ${cells.join(" | ")} |`;
  return [line(head), line(head.map(() => "---")), ...rows.map(line)].join("\n");
}

const code = (text) => `\`${text}\``;

/** One generated block per name; `system.md` places them with markers. */
export function specTables(tokens) {
  const themed2 = (value) =>
    typeof value === "object" && value !== null ? [value.light, value.dark] : [value, value];
  const px = (token) => (token.phone ? `${token.value} (${token.phone} on a phone)` : token.value);
  const range = (b) =>
    b.min && b.max ? `${b.min}–${b.max} px` : b.min ? `from ${b.min} px` : `up to ${b.max} px`;
  return {
    color: table(
      ["Token", "Light", "Dark", "Use"],
      tokens.color.tokens.map((t) => [code(t.name), ...themed2(t.value), t.usage]),
    ),
    type: table(
      ["Style", "Size / line", "Weight", "Family", "Use"],
      tokens.type.groups.flatMap((group) =>
        group.styles.map((s) => [
          code(s.name),
          `${parseInt(s.fontSize, 10)} / ${parseInt(s.lineHeight, 10)}`,
          String(s.fontWeight),
          group.family,
          s.usage,
        ]),
      ),
    ),
    spacing: table(
      ["Token", "Value", "Use"],
      tokens.spacing.tokens.map((t) => [code(t.name), t.value, t.usage]),
    ),
    radius: table(
      ["Token", "Value", "Use"],
      tokens.radius.tokens.map((t) => [code(t.name), t.value, t.usage]),
    ),
    shadow: table(
      ["Token", "Light", "Dark", "Use"],
      tokens.shadow.tokens.map((t) => [code(t.name), ...themed2(t.value), t.usage]),
    ),
    size: table(
      ["Token", "Value", "Use"],
      tokens.size.tokens.map((t) => [code(t.name), px(t), t.usage]),
    ),
    motion: table(
      ["Token", "Value", "Use"],
      tokens.motion.tokens.map((t) => [code(t.name), t.value, t.usage]),
    ),
    breakpoints: table(
      ["Name", "Width", "What changes"],
      tokens.breakpoints.map((b) => [b.name, range(b), b.usage]),
    ),
    contrast: table(
      ["Pair", "Light", "Dark", "Minimum", "Use"],
      contrastRows(tokens).map((row) => [
        `${code(row.fg)} on ${code(row.bg)}`,
        `${row.light.toFixed(1)}:1`,
        `${row.dark.toFixed(1)}:1`,
        `${row.min}:1`,
        row.use,
      ]),
    ),
  };
}

const MARKER = /<!-- generated:([a-z]+):start -->[\s\S]*?<!-- generated:\1:end -->/g;

/** `system.md` with every marked block replaced by its current table. */
export function renderSpec(tokens, current) {
  if (current === null) throw new Error("v3/docs/design/system.md is missing");
  const tables = specTables(tokens);
  const seen = new Set();
  const text = current.replace(MARKER, (_, name) => {
    if (!(name in tables)) throw new Error(`system.md: no generated table named "${name}"`);
    seen.add(name);
    return `<!-- generated:${name}:start -->\n${tables[name]}\n<!-- generated:${name}:end -->`;
  });
  const missing = Object.keys(tables).filter((name) => !seen.has(name));
  if (missing.length > 0) {
    throw new Error(`system.md has no <!-- generated:…:start/end --> block for: ${missing.join(", ")}`);
  }
  return text;
}

const OUTPUTS = [
  [WEB_OUT, renderWebCss],
  [DOCS_OUT, renderDocsCss],
  [SPEC_OUT, renderSpec],
];

function main() {
  const check = process.argv.includes("--check");
  const tokens = load();
  const stale = [];
  const failures = contrastFailures(tokens);
  if (failures.length > 0) {
    console.error(`gen-tokens: colour pairs below their minimum contrast:\n  ${failures.join("\n  ")}`);
    process.exit(1);
  }
  for (const [path, render] of OUTPUTS) {
    let current = null;
    try {
      current = readFileSync(path, "utf-8");
    } catch {
      current = null;
    }
    const wanted = render(tokens, current);
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
  if (check) {
    console.log(
      "gen-tokens: generated files match tokens.json; every colour pair reaches its minimum contrast.",
    );
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
