import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "playwright/test";

test("shared interface edits persist to project TOML and assets use authenticated previews", async ({ page, browser, request }, testInfo) => {
  const connectionFile = process.env.TINYSOUL_E2E_CONNECTION!;
  const connection = JSON.parse(readFileSync(connectionFile, "utf-8")) as { address: string; token: string };
  const project = path.join(path.dirname(connectionFile), "project");
  const assetPath = path.join(project, "presentation/assets/images/sample.png");
  mkdirSync(path.dirname(assetPath), { recursive: true });
  writeFileSync(assetPath, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1sAAAAASUVORK5CYII=", "base64"));
  const base = `http://${connection.address}/v2`;
  const headers = { Authorization: `Bearer ${connection.token}` };
  const before = await (await request.get(`${base}/status`, { headers })).json();
  const activations: string[] = [];
  page.on("request", (sent) => {
    if (/\/v2\/config\/(apply|reload)$/.test(sent.url())) activations.push(sent.url());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(connection.address);
  await page.locator('input[type="password"]').fill(connection.token);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByTitle("Settings", { exact: true }).click();
  await page.getByRole("button", { name: "界面", exact: true }).last().click();
  await expect(page.getByRole("button", { name: "深色", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.locator("select").first().selectOption("serif");
  await page.getByRole("spinbutton").first().fill("16");
  await page.getByRole("spinbutton").first().press("Enter");
  await expect(page.getByText("已保存到项目", { exact: true })).toBeVisible();
  const configPath = path.join(project, "presentation/configs/interface.toml");
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/font_size\s*=\s*16/);
  expect(readFileSync(configPath, "utf-8")).toMatch(/font_sans\s*=\s*"serif"/);
  expect(readFileSync(configPath, "utf-8")).toMatch(/theme\s*=\s*"dark"/);

  await page.getByTitle("Switch to light theme", { exact: true }).click();
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/theme\s*=\s*"light"/);
  await page.getByTitle("Switch to dark theme", { exact: true }).click();
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/theme\s*=\s*"dark"/);
  expect(readFileSync(configPath, "utf-8")).toMatch(/font_sans\s*=\s*"serif"/);

  await page.getByText("项目共享资产", { exact: true }).click();
  await page.getByRole("button", { name: /images\/sample.png/ }).click();
  const image = page.getByRole("img", { name: "images/sample.png" });
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBe(1);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: /下载|Download/ }).click();
  expect((await downloadEvent).suggestedFilename()).toBe("sample.png");
  await page.screenshot({ path: testInfo.outputPath("shared-interface-and-assets.png") });

  const other = await browser.newContext();
  try {
    await other.addInitScript((target) => localStorage.setItem("tinysoul-web-connection", JSON.stringify(target)), connection);
    const second = await other.newPage();
    await second.goto("/");
    await expect(second.locator("html")).toHaveClass(/dark/);
    await expect.poll(() => second.locator("html").evaluate((element) => (element as HTMLElement).style.getPropertyValue("--ui-font-size"))).toBe("16px");
  } finally {
    await other.close();
  }
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  const after = await (await request.get(`${base}/status`, { headers })).json();
  expect(after.runtime.generation_id).toBe(before.runtime.generation_id);
  expect(activations).toEqual([]);
});
