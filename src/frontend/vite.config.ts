import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load environment variables (such as VITE_BACKEND_URL) from environment or .env files
  const env = loadEnv(mode, process.cwd(), '');
  const backendUrl = env.VITE_BACKEND_URL;

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // If VITE_BACKEND_URL is provided, proxy requests matching /api/v1 to that target URL.
      // Otherwise, no backend port is hardcoded.
      proxy: backendUrl
        ? {
            '/api/v1': {
              target: backendUrl,
              changeOrigin: true,
              secure: false,
            },
          }
        : undefined,
    },
  };
});
