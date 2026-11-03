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
            // Strictly guard proxy header rewrite using underlying socket connection evidence
            const remoteIp = req.socket?.remoteAddress || '';
            const isLoopbackIp =
              remoteIp === '127.0.0.1' ||
              remoteIp === '::1' ||
              remoteIp === '::ffff:127.0.0.1';

            const clientHost = req.headers['host'] || '';
            const isLocalHost =
              clientHost.startsWith('localhost:') ||
              clientHost.startsWith('127.0.0.1:') ||
              clientHost === 'localhost' ||
              clientHost === '127.0.0.1';

            const incomingOrigin = req.headers['origin'];
            const isLocalOrigin =
              !incomingOrigin ||
              incomingOrigin === 'http://localhost:5173' ||
              incomingOrigin === 'http://127.0.0.1:5173';

            // Only rewrite when socket connection, host, and origin are all verified loopback
            if (isLoopbackIp && isLocalHost && isLocalOrigin) {
              proxyReq.setHeader('Origin', 'http://127.0.0.1:8000');
              proxyReq.setHeader('Sec-Fetch-Site', 'same-origin');
            }
          });
        },
      },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const remoteIp = req.socket?.remoteAddress || '';
            const isLoopbackIp =
              remoteIp === '127.0.0.1' ||
              remoteIp === '::1' ||
              remoteIp === '::ffff:127.0.0.1';

            const clientHost = req.headers['host'] || '';
            const isLocalHost =
              clientHost.startsWith('localhost:') ||
              clientHost.startsWith('127.0.0.1:') ||
              clientHost === 'localhost' ||
              clientHost === '127.0.0.1';

            const incomingOrigin = req.headers['origin'];
            const isLocalOrigin =
              !incomingOrigin ||
              incomingOrigin === 'http://localhost:4173' ||
              incomingOrigin === 'http://127.0.0.1:4173';

            if (isLoopbackIp && isLocalHost && isLocalOrigin) {
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

