import { createRequire } from "node:module";
import { cpSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

/**
 * On-demand evidence build for the code block renderers (F0/W2): builds ONLY
 * the dev-only codeblocks verification entry into an isolated outDir to show
 * that the mermaid renderer is emitted as lazy async chunks (not part of the
 * entry chunk) and that the tikzjax runtime ships alongside the bundle.
 *
 * Not part of `pnpm build`. Run from visualization/:
 *   pnpm exec vite build --config test/e2e/vite.bundle-evidence.config.ts
 */

const visualizationRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(visualizationRoot, "package.json"));

function tikzjaxCopy(): Plugin {
  const distDir = path.join(
    path.dirname(require.resolve("@drgrice1/tikzjax/package.json")),
    "dist",
  );
  return {
    name: "tikzjax-copy-evidence",
    writeBundle() {
      cpSync(distDir, path.resolve("../../.local-test/codeblocks-dist/tikzjax"), {
        recursive: true,
        filter: (source) => !source.endsWith(".map"),
      });
    },
  };
}

export default defineConfig({
  plugins: [tikzjaxCopy()],
  build: {
    outDir: "../../.local-test/codeblocks-dist",
    emptyOutDir: true,
    rollupOptions: {
      input: { codeblocksDev: path.join(visualizationRoot, "codeblocks-dev.html") },
    },
  },
});
