import { expect, test, type Page } from "playwright/test";

/**
 * Real-browser verification for MermaidBlock / TikZBlock against the vite
 * dev server (F0 / W2). Asserts actual SVG output, local-only asset loading
 * and bounded failure fallbacks. Nothing here is mocked.
 */

const PAGE = "/codeblocks-dev.html";

async function collectPage(page: Page) {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  const requestUrls: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("requestfailed", (req) => {
    // The tikzjax invalid-case fallback is a designed marker image pointing
    // at //invalid.site; its fetch is expected to fail (and whether it fires
    // inside the test window is timing/DNS dependent).
    if (req.url().startsWith("http://invalid.site/")) return;
    failedRequests.push(`${req.url()} :: ${req.failure()?.errorText ?? "?"}`);
  });
  page.on("requestfinished", (req) => requestUrls.push(req.url()));
  return { consoleErrors, pageErrors, failedRequests, requestUrls };
}

test("mermaid / tikzjax 在真实浏览器中产出 SVG，资源全部本地", async ({ page }) => {
  const obs = await collectPage(page);
  await page.goto(PAGE);

  // Mermaid: valid diagram renders real SVG via the official render API.
  const mermaidOk = page.locator('[data-case="mermaid-valid"] [data-block="mermaid"]');
  await expect(mermaidOk).toHaveAttribute("data-status", "done", { timeout: 60_000 });
  const mermaidSvg = mermaidOk.locator(".cb-diagram svg");
  await expect(mermaidSvg).toBeVisible();
  await expect(mermaidSvg.locator("g.node, .node, [id^='flowchart']").first()).toBeAttached();

  // Mermaid: invalid source keeps source text and a bounded error.
  const mermaidBad = page.locator('[data-case="mermaid-invalid"] [data-block="mermaid"]');
  await expect(mermaidBad).toHaveAttribute("data-status", "error", { timeout: 60_000 });
  await expect(mermaidBad.locator(".cb-frame-error")).toBeVisible();
  await expect(mermaidBad.locator(".cb-frame-source code")).toContainText("flowchart");

  // TikZ: real wasm compile inside the isolated iframe produces SVG.
  const tikzOk = page.locator('[data-case="tikz-valid"] [data-block="tikz"]');
  await expect(tikzOk).toHaveAttribute("data-status", "done", { timeout: 180_000 });
  const tikzSvg = tikzOk.locator(".cb-diagram svg");
  await expect(tikzSvg).toBeAttached();
  await expect(tikzSvg.locator("path").first()).toBeAttached();

  // TikZ: invalid source falls back to source + bounded error.
  const tikzBad = page.locator('[data-case="tikz-invalid"] [data-block="tikz"]');
  await expect(tikzBad).toHaveAttribute("data-status", "error", { timeout: 180_000 });
  await expect(tikzBad.locator(".cb-frame-error")).toBeVisible();
  await expect(tikzBad.locator(".cb-frame-source code")).toContainText("tikzpicture");

  // Offline delivery: the tikzjax runtime/worker/wasm/core/fonts all came
  // from the dev server itself, and nothing was fetched from a CDN.
  const tikzAssets = obs.requestUrls.filter((url) => url.includes("/tikzjax/"));
  for (const required of ["tikzjax.js", "run-tex.js", "tex.wasm.gz", "core.dump.gz", "fonts.css"]) {
    expect(
      tikzAssets.some((url) => url.includes(required)),
      `missing local tikzjax asset ${required}`,
    ).toBe(true);
  }
  const external = obs.requestUrls.filter((url) => {
    if (url.startsWith("data:")) return false;
    // The tikzjax invalid-case marker image (//invalid.site) is the runtime's
    // designed failure signal, not a CDN fetch.
    if (url.startsWith("http://invalid.site/")) return false;
    try {
      // blob:<origin>/... URLs report the embedding origin.
      return new URL(url).origin !== "http://127.0.0.1:5199";
    } catch {
      return true;
    }
  });
  expect(external, `external requests: ${external.join(", ")}`).toEqual([]);

  // No uncaught exceptions; every request succeeded. Expected renderer
  // errors (mermaid parse error, TeX compile log) are recorded, not fatal.
  expect(obs.pageErrors, obs.pageErrors.join("\n")).toEqual([]);
  expect(obs.failedRequests, obs.failedRequests.join("\n")).toEqual([]);
  console.log("[codeblocks] console error entries (expected renderer failures included):");
  for (const line of obs.consoleErrors) console.log(`  ${line.slice(0, 300)}`);
  console.log(`[codeblocks] total requests: ${obs.requestUrls.length}, tikzjax assets: ${tikzAssets.length}`);
});
