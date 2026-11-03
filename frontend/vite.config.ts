/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            // Strictly guard proxy header rewrite to local development requests only
            const clientHost = req.headers['host'] || '';
            const isLocal =
              clientHost.startsWith('localhost:') ||
              clientHost.startsWith('127.0.0.1:') ||
              clientHost === 'localhost' ||
              clientHost === '127.0.0.1';

            if (isLocal) {
              proxyReq.setHeader('Origin', 'http://127.0.0.1:8000');
              proxyReq.setHeader('Sec-Fetch-Site', 'same-origin');
            }
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    emptyOutDir: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
});

