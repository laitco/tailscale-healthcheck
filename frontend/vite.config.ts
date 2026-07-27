import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  base: '/static/app/',
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: (assetInfo) =>
          assetInfo.names?.[0]?.endsWith('.css') ? 'app.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    proxy: {
      '/health': 'http://localhost:5000',
      '/keys': 'http://localhost:5000',
      '/admin': 'http://localhost:5000',
    },
  },
})
