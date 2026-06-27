import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";


export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        dashboard: resolve(__dirname, "index.html"),
        landing: resolve(__dirname, "landing.html"),
      },
    },
  },
  plugins: [react()],
});
