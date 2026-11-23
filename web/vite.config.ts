import { defineConfig, type Plugin } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { rmSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// The demo reads the CLI registry (boards, packs) from ../src/openguildkit/registry,
// so the dev server must be allowed to serve the parent folder.
//
// OGK_API=http://ogk-….localhost:7311 (the origin of the address `openguildkit ui --no-browser` printed) forwards
// /api to that server: the page then opens the real project with hot reload. The proxy presents the page as the
// server's own host and origin, which the server requires for every API call.
const api = process.env.OGK_API;

// The images that only the Atelier Nova demo shows. The product build (npm run build, which the wheel
// ships) leaves them out with the demo code.
const DEMO_ASSETS = ['assets/world', 'assets/characters'];

function dropDemoAssets(): Plugin {
  let outDir = '';
  return {
    name: 'openguildkit-drop-demo-assets',
    apply: 'build',
    configResolved(config) { outDir = resolve(config.root, config.build.outDir); },
    closeBundle() { for (const folder of DEMO_ASSETS) rmSync(resolve(outDir, folder), { recursive: true, force: true }); },
  };
}

export default defineConfig(({ command, mode }) => {
  // `npm run dev` and `npm run build:demo` include the demo; `npm run build` (what `openguildkit ui` serves) does not.
  const demo = command === 'serve' || mode === 'demo';
  return {
    plugins: [react(), ...(demo ? [] : [dropDemoAssets()])],
    define: { __OGK_DEMO__: JSON.stringify(demo) },
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
          codeSplitting: {
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
    test: { include: ['tests/domain/**/*.test.ts', 'tests/project/**/*.test.ts', 'tests/scripts/**/*.test.mjs'], environment: 'node' },
  };
});
