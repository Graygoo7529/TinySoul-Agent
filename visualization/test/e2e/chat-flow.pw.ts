import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "playwright/test";
import { protocolText, t } from "../../src/i18n/core";
import type { Locale } from "../../src/i18n/types";

/** Real Agent/owners/HTTP/WS with only the model output scripted. */
const here = path.dirname(fileURLToPath(import.meta.url));
const connectionFile = path.resolve(here, "../../../.local-test/e2e-backend/connection.json");
const BACKEND_WAIT = 30_000;
const QUESTION_TEXT = "Which option do you pick?";

interface BackendConnection {
  address: string;
  token: string;
}

function backendConnection(): BackendConnection {
  return JSON.parse(readFileSync(process.env.TINYSOUL_E2E_CONNECTION ?? connectionFile, "utf-8")) as BackendConnection;
}

test.beforeEach(async ({ request }) => {
  const { address, token } = backendConnection();
  const response = await request.patch(`http://${address}/v2/presentation/configs/interface`, {
    headers: { Authorization: `Bearer ${token}` }, data: { changes: { locale: "zh-CN" } },
  });
  expect(response.ok()).toBe(true);
});

async function connect(page: Page): Promise<void> {
  const { address, token } = backendConnection();
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(address);
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: t("connection.connect") }).click();
  await expect(page.getByPlaceholder(t("chat.composer.newTurn"))).toBeEnabled({ timeout: BACKEND_WAIT });
}

function questionDock(page: Page) {
  return page.getByRole("dialog", { name: t("chat.waitingReply") });
}

async function switchLocale(page: Page, from: Locale, to: Locale) {
  await page.getByTitle(t("shell.settings", undefined, from), { exact: true }).click();
  await page.getByRole("button", { name: t("settings.page.interface.title", undefined, from), exact: true }).last().click();
  await page.getByRole("button", { name: t(to === "en-US" ? "settings.locale.enUS" : "settings.locale.zhCN", undefined, from), exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", to);
  await page.getByTitle(t("shell.chat", undefined, to), { exact: true }).click();
}

test("user conversation: answer, question reply and Session recovery", async ({ page }, testInfo) => {
  const runId = Date.now().toString(36);
  const plainText = `e2e-plain hello ${runId}`;
  const askText = `e2e-ask pick one ${runId}`;
  const commentText = `e2e-reply-comment ${runId}`;
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await connect(page);

  const composer = page.getByPlaceholder(t("chat.composer.newTurn"));
  await composer.fill(plainText);
  await composer.press("Enter");
  await expect(page.locator(".bubble-user", { hasText: plainText })).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(page.locator(".answer-card", { hasText: `You said: ${plainText}.` })).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(page.locator(".answer-card")).toHaveCount(1);

  await composer.fill(askText);
  await composer.press("Enter");
  const dock = questionDock(page);
  await expect(dock.getByText(QUESTION_TEXT, { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(dock.locator('input[type="radio"]')).toHaveCount(2);
  const earlier = page.getByRole("button", { name: t("chat.allSteps") });
  if (await earlier.count()) await earlier.click();
  await expect(page.locator(".steps-viewport")).toContainText("home:top/skills/review", { timeout: BACKEND_WAIT });
  await expect(page.locator('[data-activity-gist="result"]')).toContainText("baseline-output-ready", { timeout: BACKEND_WAIT });

  for (const locale of ["zh-CN", "en-US"] as const) {
    if (locale === "en-US") await switchLocale(page, "zh-CN", locale);
    const readResult = page.locator('[data-activity-gist="result"]').filter({ hasText: "baseline-output-ready" });
    await readResult.getByRole("button", { name: t("common.details", undefined, locale), exact: true }).click();
    const detail = page.getByRole("dialog", { name: "workspace.read", exact: true });
    await expect(detail.getByText(t("trace.processingStep", undefined, locale), { exact: true })).toBeVisible();
    await expect(detail.getByText(protocolText("action.stage.execute", locale)!, { exact: true })).toBeVisible();
    await detail.getByRole("button", { name: t("settings.callParams", undefined, locale), exact: true }).click();
    await expect(detail).toContainText("baseline-output-ready");
    await page.setViewportSize({ width: 420, height: 900 });
    await page.screenshot({ path: testInfo.outputPath(`action-detail-${locale}-narrow.png`), animations: "disabled" });
    await detail.getByRole("button", { name: t("common.close", undefined, locale), exact: true }).click();
    await page.setViewportSize({ width: 1280, height: 900 });
  }
  await switchLocale(page, "en-US", "zh-CN");

  await dock.locator("label", { hasText: "Option B" }).click();
  await dock.getByPlaceholder(t("chat.question.additionalThoughts")).fill(commentText);
  await dock.getByRole("button", { name: t("chat.question.reply"), exact: true }).click();
  await expect(dock).toHaveCount(0, { timeout: BACKEND_WAIT });
  const answered = page.locator('[data-question-form="readonly"]', { hasText: QUESTION_TEXT });
  await expect(answered).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(answered.getByText("Option B", { exact: true })).toBeVisible();
  await expect(answered).toContainText(commentText);
  await expect(page.locator(".answer-card", { hasText: "You picked Option B (opt_b)." })).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(page.locator(".answer-card", { hasText: commentText })).toHaveCount(1);

  await page.reload();
  await expect(page.locator(".answer-card")).toHaveCount(2, { timeout: BACKEND_WAIT });
  await expect(page.locator(".bubble-user", { hasText: plainText })).toHaveCount(1);
  await expect(page.locator(".bubble-user", { hasText: askText })).toHaveCount(1);
  await expect(page.locator('[data-question-form="readonly"]', { hasText: QUESTION_TEXT })).toContainText(commentText);
  await expect(page.getByPlaceholder(t("chat.composer.newTurn"))).toBeEnabled();
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
});

test("Reflection: shared question flow completes without a User Session record", async ({ page, request }) => {
  const { address, token } = backendConnection();
  const base = `http://${address}/v2`;
  const headers = { Authorization: `Bearer ${token}` };
  const before = await (await request.get(`${base}/session/turns`, { headers })).json();
  await connect(page);
  await page.getByRole("button", { name: t("shell.organize"), exact: true }).click();
  await page.getByRole("textbox", { name: t("resources.instructionInput"), exact: true }).fill("e2e-reflection: review Home with my confirmation");
  const receiptPromise = page.waitForResponse((response) => response.url().endsWith("/v2/reflection") && response.request().method() === "POST");
  await page.getByRole("button", { name: t("resources.startHomeReflection") }).click();
  const receipt = await (await receiptPromise).json();
  expect(typeof receipt.request_id).toBe("string");
  const card = page.locator('[data-reflection="home"]');
  const dock = questionDock(page);
  await expect(card.getByText(`${t("shell.home")} ${t("shell.organize")}`, { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(dock.getByText("Continue this reflection?", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(card.locator(".live-border")).toHaveCount(1);

  await page.reload();
  await expect(dock.getByText("Continue this reflection?", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(card.locator(".live-border")).toHaveCount(1);
  await dock.locator("label", { hasText: "Option A" }).click();
  await dock.getByPlaceholder(t("chat.question.additionalThoughts")).fill("e2e-reply-comment confirmed");
  await dock.getByRole("button", { name: t("chat.question.reply"), exact: true }).click();
  await expect(card.getByText(t("chat.reflection.completed"), { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(card.getByText("Reflection reviewed with your reply.", { exact: true })).toBeVisible();
  await expect(card.locator(".answer-card")).toHaveCount(0);
  await expect(card.getByRole("button", { name: t("chat.reflection.stop") })).toHaveCount(0);

  const after = await (await request.get(`${base}/session/turns`, { headers })).json();
  expect(after.items.map((item: { turn_id: string }) => item.turn_id)).toEqual(before.items.map((item: { turn_id: string }) => item.turn_id));
  await page.reload();
  await expect(card.getByText(t("chat.reflection.completed"), { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
});
