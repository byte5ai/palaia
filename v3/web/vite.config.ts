import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dashboard's version comes from package.json alone — no second file
// restates it (the same single-source-of-truth rule palaia_hub.__version__
// follows on the server side).
const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8'),
) as { version: string }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // `src/lib/skills.ts` imports the shipped SKILL.md files from
    // ../../clients with `?raw` so the connect page hands over the real
    // skill rather than a copy that can drift (SPEC-207). Bundling resolves
    // them fine; the dev server needs the v3 root on its allow list.
    fs: { allow: ['..'] },
  },
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
  },
})
