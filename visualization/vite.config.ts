import { createRequire } from "node:module";
import { createReadStream, cpSync, existsSync, statSync } from "node:fs";
import path from "node:path";
import { defineConfig, type Connect, type Plugin, type ResolvedConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

const require = createRequire(import.meta.url);

const TIKZJAX_ROUTE = "/tikzjax";

const tikzjaxMime: Record<string, string> = {
  ".js": "text/javascript",
  ".css": "text/css",
  ".map": "application/json",
  ".gz": "application/octet-stream",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
};

/**
 * Serves and ships the @drgrice1/tikzjax runtime (tikzjax.js, run-tex.js,
 * tex.wasm.gz, core.dump.gz, tex_files, fonts) from the locked npm package so
 * TikZ rendering works without a CDN in both browser and Tauri builds.
 *
 * Dev: middleware serves the package dist directory at /tikzjax/*.
 * Build: the directory is copied into <outDir>/tikzjax (source maps skipped).
 */
function tikzjaxAssets(): Plugin {
  const distDir = path.join(
    path.dirname(require.resolve("@drgrice1/tikzjax/package.json")),
    "dist",
  );
  let config: ResolvedConfig;

  const serve: Connect.NextHandleFunction = (req, res, next) => {
    const urlPath = decodeURIComponent((req.url ?? "").split("?")[0]);
    const filePath = path.join(distDir, path.normalize(urlPath));
    if (!filePath.startsWith(distDir) || !existsSync(filePath) || !statSync(filePath).isFile()) {
      next();
      return;
    }
    res.setHeader(
      "Content-Type",
      tikzjaxMime[path.extname(filePath).toLowerCase()] ?? "application/octet-stream",
    );
    createReadStream(filePath).pipe(res);
  };

  return {
    name: "tinysoul-tikzjax-assets",
    configResolved(resolved) {
      config = resolved;
    },
    configureServer(server) {
      server.middlewares.use(TIKZJAX_ROUTE, serve);
    },
    writeBundle() {
      const target = path.join(config.root, config.build.outDir, TIKZJAX_ROUTE);
      cpSync(distDir, target, {
        recursive: true,
        filter: (source) => !source.endsWith(".map"),
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [react(), tailwindcss(), tikzjaxAssets()],

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
