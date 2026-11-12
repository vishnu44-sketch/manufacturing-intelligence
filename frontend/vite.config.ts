// Vite: the dev server (npm run dev, port 5173) serves the app itself at every page address and sends the
// Django addresses (the API, the admin, static files) on to the Django runserver on 8081; the build
// (npm run build) writes the app into portal/static/portal/app/, where Django serves its index.html at /
// and at every page address (its files under /static/portal/app/).
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const DJANGO = 'http://127.0.0.1:8081'
// the JSON API (also the Excel download), the Django admin and its static files
const DJANGO_PATHS = ['/api', '/admin', '/static']

export default defineConfig(({ command }) => ({
  // Tailwind CSS (src/tailwind.css: no Preflight reset, so only the restyled Ask page changes)
  plugins: [react(), tailwindcss()],
  // "@/..." is src/ (the shadcn/ui components import "@/lib/utils")
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  base: command === 'build' ? '/static/portal/app/' : '/',
  build: {
    outDir: fileURLToPath(new URL('../portal/static/portal/app', import.meta.url)),
    emptyOutDir: true, // the folder only holds this build
    chunkSizeWarningLimit: 700, // kB: the chart file (ECharts, ~670 kB) loads only when a chart is shown
  },
  server: {
    port: 5173,
    strictPort: true,
    // the Host header stays localhost:5173, so Django's CSRF origin check matches the browser's Origin
    proxy: Object.fromEntries(DJANGO_PATHS.map((path) => [path, DJANGO])),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    testTimeout: 15000, // a test may take up to 15 s: with all files running at once, the first render of a file is slow
    css: false,
  },
}))
