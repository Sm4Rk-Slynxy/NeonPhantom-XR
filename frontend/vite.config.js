import { svelte } from '@sveltejs/vite-plugin-svelte';

export default {
  plugins: [svelte()],
  build: { outDir: 'build', emptyOutDir: true, sourcemap: false },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: 'http://127.0.0.1:8321', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8321', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8321', ws: true, changeOrigin: true }
    }
  }
};
