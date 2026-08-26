/** Single source of truth for the dashboard's version: package.json,
 * injected at build time by vite.config.ts's `define`. Nothing else
 * restates it. */
export const __version__: string = __APP_VERSION__;
