import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API to the HTTPS backend; production build is served by FastAPI itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "https://localhost:8443", secure: false, changeOrigin: false } },
  },
  build: { sourcemap: false },
});
