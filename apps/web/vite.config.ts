import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { TanStackRouterVite } from "@tanstack/router-plugin/vite";

const allowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? "mnemosyne.local")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

export default defineConfig({
  plugins: [TanStackRouterVite({ quoteStyle: "double" }), react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
