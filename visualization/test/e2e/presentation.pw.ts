import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "playwright/test";
import { t } from "../../src/i18n/core";
import type { Locale } from "../../src/i18n/types";
import type { SettingsPageId } from "../../src/features/settings/pages";

async function openSettingsPage(page: Page, id: SettingsPageId, locale: Locale) {
  const picker = page.locator('.settings-picker[data-kind="pages"]');
  const trigger = picker.getByRole("button", { name: t("settings.nav.label", undefined, locale), exact: true });
  if (await trigger.isVisible()) await trigger.click();
  await picker.getByRole("button", { name: t(`settings.page.${id}.title`, undefined, locale), exact: true }).last().click();
}

test("shared interface edits persist to project TOML and assets use authenticated previews", async ({ page, browser, request }, testInfo) => {
  const connectionFile = process.env.TINYSOUL_E2E_CONNECTION!;
  const connection = JSON.parse(readFileSync(connectionFile, "utf-8")) as { address: string; token: string };
  const project = path.join(path.dirname(connectionFile), "project");
  const assetPath = path.join(project, "presentation/assets/images/sample.png");
  mkdirSync(path.dirname(assetPath), { recursive: true });
  writeFileSync(assetPath, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1sAAAAASUVORK5CYII=", "base64"));
  const base = `http://${connection.address}/v2`;
  const headers = { Authorization: `Bearer ${connection.token}` };
  expect((await request.patch(`${base}/presentation/configs/interface`, {
    headers, data: { changes: { locale: "zh-CN" } },
  })).ok()).toBe(true);
  const before = await (await request.get(`${base}/status`, { headers })).json();
  const activations: string[] = [];
  page.on("request", (sent) => {
    if (/\/v2\/config\/(apply|reload)$/.test(sent.url())) activations.push(sent.url());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(connection.address);
  await page.locator('input[type="password"]').fill(connection.token);
  await page.getByRole("button", { name: t("connection.connect"), exact: true }).click();
  await page.getByTitle(t("shell.settings"), { exact: true }).click();
  await page.getByRole("button", { name: t("settings.page.interface.title"), exact: true }).last().click();
  await expect(page.getByRole("button", { name: t("settings.theme.dark"), exact: true })).toBeEnabled();
  await page.getByRole("button", { name: t("settings.theme.dark"), exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.locator("select").first().selectOption("serif");
  await page.getByRole("spinbutton").first().fill("16");
  await page.getByRole("spinbutton").first().press("Enter");
  await expect(page.getByText(t("settings.savedToProject"), { exact: true })).toBeVisible();
  const configPath = path.join(project, "presentation/configs/interface.toml");
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/font_size\s*=\s*16/);
  expect(readFileSync(configPath, "utf-8")).toMatch(/font_sans\s*=\s*"serif"/);
  expect(readFileSync(configPath, "utf-8")).toMatch(/theme\s*=\s*"dark"/);

  await page.getByTitle(t("shell.switchToLight"), { exact: true }).click();
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/theme\s*=\s*"light"/);
  await page.getByTitle(t("shell.switchToDark"), { exact: true }).click();
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/theme\s*=\s*"dark"/);
  expect(readFileSync(configPath, "utf-8")).toMatch(/font_sans\s*=\s*"serif"/);

  await page.getByText(t("settings.projectSharedAssets"), { exact: true }).click();
  await page.getByRole("button", { name: /images\/sample.png/ }).click();
  const image = page.getByRole("img", { name: "images/sample.png" });
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBe(1);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: t("settings.download"), exact: true }).click();
  expect((await downloadEvent).suggestedFilename()).toBe("sample.png");
  await page.screenshot({ path: testInfo.outputPath("shared-interface-and-assets.png"), animations: "disabled" });

  await page.getByRole("button", { name: t("settings.locale.enUS"), exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en-US");
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/locale\s*=\s*"en-US"/);

  for (const locale of ["en-US", "zh-CN"] as const) {
    await page.getByRole("button", { name: t("settings.locale.enUS", undefined, locale), exact: true }).waitFor();
    if (locale === "zh-CN") {
      await page.getByRole("button", { name: t("settings.locale.zhCN", undefined, "en-US"), exact: true }).click();
      await expect(page.locator("html")).toHaveAttribute("lang", locale);
    }
    await page.setViewportSize({ width: 420, height: 900 });
    await openSettingsPage(page, "context", locale);
    await expect(page.getByText(t("settings.currentContextUsage", undefined, locale), { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`context-${locale}-narrow.png`), fullPage: true, animations: "disabled" });
    await openSettingsPage(page, "phase-bindings", locale);
    await expect(page.locator("select").first()).toBeEnabled();
    await expect(page.locator("select").first().locator('option[value=""]')).toHaveText(t("settings.phaseBindings.useDefault", undefined, locale));
    await page.screenshot({ path: testInfo.outputPath(`phase-bindings-${locale}-narrow.png`), fullPage: true, animations: "disabled" });
    await openSettingsPage(page, "credentials", locale);
    await expect(page.getByText(t("settings.credentialsTitle", undefined, locale), { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`credentials-${locale}-narrow.png`), fullPage: true, animations: "disabled" });
    await openSettingsPage(page, "interface", locale);
  }
  await page.getByRole("button", { name: t("settings.locale.enUS"), exact: true }).click();
  await expect.poll(() => readFileSync(configPath, "utf-8")).toMatch(/locale\s*=\s*"en-US"/);

  const other = await browser.newContext();
  try {
    await other.addInitScript((target) => localStorage.setItem("tinysoul-web-connection", JSON.stringify(target)), connection);
    const second = await other.newPage();
    await second.goto("/");
    await expect(second.locator("html")).toHaveClass(/dark/);
    await expect(second.locator("html")).toHaveAttribute("lang", "en-US");
    await expect.poll(() => second.locator("html").evaluate((element) => (element as HTMLElement).style.getPropertyValue("--ui-font-size"))).toBe("16px");
  } finally {
    await other.close();
  }
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en-US");
  const after = await (await request.get(`${base}/status`, { headers })).json();
  expect(after.runtime.generation_id).toBe(before.runtime.generation_id);
  expect(activations).toEqual([]);
});
