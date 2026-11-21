import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// The demo reads the CLI registry (boards, packs) from ../src/openguildkit/registry,
// so the dev server must be allowed to serve the parent folder.
//
// OGK_API=http://127.0.0.1:7311 forwards /api to a running `openguildkit ui --no-browser`: the page then
// opens the real project with hot reload. The proxy presents the page as the server's own origin, which
// the server requires for every API call.
const api = process.env.OGK_API;

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5199,
    fs: { allow: ['..'] },
    proxy: api ? {
      '/api': {
        target: api,
        changeOrigin: true,
        configure: (proxy) => proxy.on('proxyReq', (request) => { request.setHeader('origin', api.replace(/\/$/, '')); }),
      },
    } : undefined,
  },
  preview: { port: 5198 },
  base: './',
  build: {
    rolldownOptions: {
      output: {
        advancedChunks: {
          groups: [
            { name: 'react', test: /node_modules[\/](react|react-dom|scheduler)[\/]/ },
            { name: 'demo-catalogue', test: /fixtures[\/]catalogue\.json/ },
            // The demo reads the CLI registry (packs and boards) and checks its data with Zod.
            { name: 'demo-registry', test: /openguildkit[\/]registry[\/]/ },
            { name: 'zod', test: /node_modules[\/]zod[\/]/ },
          ],
        },
      },
    },
  },
  test: { include: ['tests/domain/**/*.test.ts', 'tests/project/**/*.test.ts'], environment: 'node' },
});
