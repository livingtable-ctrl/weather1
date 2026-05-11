import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],

  // Asset paths in the built HTML will be prefixed with /static/dist/
  // so Flask's default static handler can serve them without extra config.
  base: '/static/dist/',

  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },

  server: {
    port: 5173,
    proxy: {
      // During `npm run dev`, forward all /api/* calls to Flask.
      // The browser only talks to localhost:5173 — no CORS headers needed.
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
});
