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
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // server.py enforces local loopback same-origin:
            // 1. Host header port must match server bind port (handled by changeOrigin)
            // 2. Origin header must be absent or match "http://" + Host
            // 3. Sec-Fetch-Site header must not be "cross-site"
            proxyReq.setHeader('Origin', 'http://127.0.0.1:8000');
            proxyReq.setHeader('Sec-Fetch-Site', 'same-origin');
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

