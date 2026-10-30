import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "playwright/test";

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

async function connect(page: Page): Promise<void> {
  const { address, token } = backendConnection();
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(address);
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByPlaceholder("Message TinySoul…")).toBeEnabled({ timeout: BACKEND_WAIT });
}

function questionDock(page: Page) {
  return page.getByRole("dialog", { name: "Waiting for your reply" });
}

test("user conversation: answer, question reply and Session recovery", async ({ page }) => {
  const runId = Date.now().toString(36);
  const plainText = `e2e-plain hello ${runId}`;
  const askText = `e2e-ask pick one ${runId}`;
  const commentText = `e2e-reply-comment ${runId}`;
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await connect(page);

  const composer = page.getByPlaceholder("Message TinySoul…");
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
  const earlier = page.getByRole("button", { name: /earlier steps|Show all steps/ });
  if (await earlier.count()) await earlier.click();
  await expect(page.locator(".steps-viewport")).toContainText("home:top/skills/review", { timeout: BACKEND_WAIT });
  await expect(page.locator('[data-activity-gist="result"]')).toContainText("baseline-output-ready", { timeout: BACKEND_WAIT });

  await dock.locator("label", { hasText: "Option B" }).click();
  await dock.getByPlaceholder("Additional thoughts (optional)…").fill(commentText);
  await dock.getByRole("button", { name: "Reply", exact: true }).click();
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
  await expect(page.getByPlaceholder("Message TinySoul…")).toBeEnabled();
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
});

test("Reflection: shared question flow completes without a User Session record", async ({ page, request }) => {
  const { address, token } = backendConnection();
  const base = `http://${address}/v2`;
  const headers = { Authorization: `Bearer ${token}` };
  const before = await (await request.get(`${base}/session/turns`, { headers })).json();
  await connect(page);
  await page.getByRole("button", { name: "整理", exact: true }).click();
  await page.getByLabel("Reflection instructions").fill("e2e-reflection: review Home with my confirmation");
  const receiptPromise = page.waitForResponse((response) => response.url().endsWith("/v2/reflection") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Start Home reflection" }).click();
  const receipt = await (await receiptPromise).json();
  expect(typeof receipt.request_id).toBe("string");
  const card = page.locator('[data-reflection="home"]');
  const dock = questionDock(page);
  await expect(card.getByText("Home 整理", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(dock.getByText("Continue this reflection?", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(card.locator(".live-border")).toHaveCount(1);

  await page.reload();
  await expect(dock.getByText("Continue this reflection?", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(card.locator(".live-border")).toHaveCount(1);
  await dock.locator("label", { hasText: "Option A" }).click();
  await dock.getByPlaceholder("Additional thoughts (optional)…").fill("e2e-reply-comment confirmed");
  await dock.getByRole("button", { name: "Reply", exact: true }).click();
  await expect(card.getByText("整理完成", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
  await expect(card.getByText("Reflection reviewed with your reply.", { exact: true })).toBeVisible();
  await expect(card.locator(".answer-card")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "停止整理" })).toHaveCount(0);

  const after = await (await request.get(`${base}/session/turns`, { headers })).json();
  expect(after.items.map((item: { turn_id: string }) => item.turn_id)).toEqual(before.items.map((item: { turn_id: string }) => item.turn_id));
  await page.reload();
  await expect(card.getByText("整理完成", { exact: true })).toBeVisible({ timeout: BACKEND_WAIT });
});
