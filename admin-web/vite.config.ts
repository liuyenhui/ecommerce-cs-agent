import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const target = mode === "system" ? "system" : "customer";
  const entryDir = target === "system" ? "system-admin" : "customer-admin";
  const projectRoot = __dirname;
  const appRoot = path.resolve(projectRoot, entryDir);

  return {
    root: appRoot,
    plugins: [react()],
    build: {
      outDir: path.resolve(projectRoot, "dist", target),
      emptyOutDir: true,
      rollupOptions: {
        input: {
          index: path.resolve(appRoot, "index.html")
        }
      }
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      fs: {
        allow: [projectRoot]
      },
      proxy: {
        "/v1": "http://localhost:8000",
        "/health": "http://localhost:8000"
      }
    }
  };
});
