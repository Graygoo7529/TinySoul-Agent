import { mkdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "playwright/test";

/**
 * F7-B visual review (plan §24.1): representative pages against the real
 * backend harness (real Agent/owners/HTTP/WS, scripted model — nothing in the
 * frontend or the transport is mocked). Every screenshot lands in
 * .local-test/visual-review/; screenshots support a human visual check.
 *
 * Runs under visual-review.config.ts only; the guarded chat-flow/codeblocks
 * config ignores this spec.
 */

const here = path.dirname(fileURLToPath(import.meta.url));
const connectionFile = path.resolve(
  here,
  "../../../.local-test/e2e-backend/connection.json",
);
const shotsDir = path.resolve(here, "../../.local-test/visual-review");

interface BackendConnection {
  address: string;
  token: string;
}

function backendConnection(): BackendConnection {
  return JSON.parse(readFileSync(process.env.TINYSOUL_E2E_CONNECTION ?? connectionFile, "utf-8")) as BackendConnection;
}

const BACKEND_WAIT = 30_000;
/** Real 1440×900 UI pages are well above this; a blank capture is not. */
const MIN_PNG_BYTES = 15_000;

async function shot(page: Page, name: string): Promise<void> {
  const file = path.join(shotsDir, `${name}.png`);
  await page.screenshot({ path: file });
  const size = statSync(file).size;
  expect(size, `${name}.png looks blank (${size} bytes)`).toBeGreaterThan(
    MIN_PNG_BYTES,
  );
}

async function connect(page: Page): Promise<void> {
  const { address, token } = backendConnection();
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(address);
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Start a conversation")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await expect(page.getByTitle("Workspace", { exact: true })).toBeEnabled();
}

test("F7-B 代表性页面视觉核对截图", async ({ page }) => {
  test.setTimeout(300_000);
  mkdirSync(shotsDir, { recursive: true });
  const runId = Date.now().toString(36);
  const plainText = `e2e-plain visual review ${runId}`;
  const askText = `e2e-ask visual review ${runId}`;
  const commentText = `e2e-reply-comment visual ${runId}`;
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  // --- Chat, light theme -------------------------------------------------
  await connect(page);
  await shot(page, "01-chat-empty-light");

  const composer = page.getByPlaceholder("Message TinySoul…");
  await composer.fill(plainText);
  await composer.press("Enter");
  await expect(
    page.locator(".answer-card", { hasText: `You said: ${plainText}.` }),
  ).toHaveCount(1, { timeout: BACKEND_WAIT });
  // Let the typewriter + settle wipe reach the document state.
  await page.waitForTimeout(2600);
  await shot(page, "02-chat-answer-light");

  await composer.fill(askText);
  await composer.press("Enter");
  await expect(page.getByText("Which option do you pick?")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await page.waitForTimeout(600);
  await shot(page, "03-chat-question-light");

  // --- Context drawer (the waiting turn is still active) ------------------
  await page.getByRole("button", { name: "Context", exact: true }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.locator("section button").first()).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await page.waitForTimeout(500);
  await shot(page, "04-context-overview-light");

  await drawer.locator("section button").first().click();
  await expect(
    page.getByRole("button", { name: "Back", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(900);
  await shot(page, "05-context-segment-light");
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await expect(drawer).toHaveCount(0);

  // --- Answer the question, then dark theme -------------------------------
  await page.locator("label", { hasText: "Option B" }).click();
  await page.getByPlaceholder("Comment (optional)…").fill(commentText);
  await page.getByRole("button", { name: "Reply" }).click();
  await expect(
    page.locator(".answer-card", {
      hasText: "You picked Option B (opt_b).",
    }),
  ).toHaveCount(1, { timeout: BACKEND_WAIT });
  await page.waitForTimeout(2600);

  await page.getByTitle("Switch to dark theme", { exact: true }).click();
  await page.waitForTimeout(400);
  await shot(page, "06-chat-conversation-dark");

  await page.reload();
  await expect(page.locator(".answer-card")).toHaveCount(2, {
    timeout: BACKEND_WAIT,
  });
  await page.waitForTimeout(400);
  await shot(page, "07-chat-continuous-dark");
  await page.getByTitle("Switch to light theme", { exact: true }).click();
  await page.waitForTimeout(300);

  // --- History: day directory + Session map -------------------------------
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "History" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Session map of this day" }).first(),
  ).toBeVisible({ timeout: BACKEND_WAIT });
  await page.waitForTimeout(400);
  await shot(page, "08-history-days-light");

  await page
    .getByRole("button", { name: "Session map of this day" })
    .first()
    .click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "Session map" }),
  ).toBeVisible();
  await page.waitForTimeout(1000);
  await shot(page, "09-history-session-map-light");
  await page.getByRole("button", { name: "Close", exact: true }).click();

  // --- Settings ------------------------------------------------------------
  await page.getByTitle("Settings", { exact: true }).click();
  await expect(page.locator("h1", { hasText: "配置状态" })).toBeVisible();
  await expect(
    page.getByText("运行配置", { exact: true }),
  ).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await page.waitForTimeout(600);
  await shot(page, "10-settings-overview-light");

  await page.getByRole("button", { name: "LLM 模型", exact: true }).click();
  await expect(page.locator("h1", { hasText: "LLM 模型" })).toBeVisible();
  await page.waitForTimeout(900);
  await shot(page, "11-settings-llm-models-light");

  await page
    .getByRole("button", { name: "Actions 与模型用途", exact: true })
    .click();
  await expect(
    page.locator("h1", { hasText: "Actions 与模型用途" }),
  ).toBeVisible();
  await page.waitForTimeout(900);
  await shot(page, "12-settings-actions-light");

  await page.getByRole("button", { name: "运行方案", exact: true }).click();
  await expect(page.locator("h1", { hasText: "运行方案" })).toBeVisible();
  await page.waitForTimeout(900);
  await shot(page, "13-settings-plans-light");

  // --- Home ----------------------------------------------------------------
  await page.getByTitle("Home", { exact: true }).click();
  await expect(page.getByText("What the next run uses")).toBeVisible();
  await page.getByRole("button", { name: "Actual", exact: true }).click();
  const homeEntry = page.locator('main button[title^="home:"]').first();
  await expect(homeEntry).toBeVisible({ timeout: BACKEND_WAIT });
  await homeEntry.click();
  await expect(page.getByText("The document could not be read")).toHaveCount(0);
  await page.waitForTimeout(600);
  await shot(page, "14-home-actual-light");

  // --- Memory ---------------------------------------------------------------
  await page.getByTitle("Memory", { exact: true }).click();
  await expect(
    page.getByText("What the agent is recording this day", { exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(1200);
  await shot(page, "15-memory-active-light");

  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await expect(page.getByLabel("Filter knowledge")).toBeVisible();
  await page.waitForTimeout(1200);
  const memoryDoc = page.locator('main button[title^="memory:"]').first();
  if ((await memoryDoc.count()) > 0) {
    await memoryDoc.click();
    await page.waitForTimeout(900);
  }
  await shot(page, "16-memory-knowledge-light");

  // --- Workspace -------------------------------------------------------------
  await page.getByTitle("Workspace", { exact: true }).click();
  await page.waitForTimeout(1500);
  await shot(page, "17-workspace-light");

  // --- Runtime observation -----------------------------------------------------
  await page.getByTitle("Runtime", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Execution", exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(1200);
  await shot(page, "18-runtime-execution-light");

  await page.getByRole("button", { name: "Jobs", exact: true }).click();
  await page.waitForTimeout(1000);
  await shot(page, "19-runtime-jobs-light");

  await page.getByRole("button", { name: "MCP", exact: true }).click();
  await page.waitForTimeout(1000);
  await shot(page, "20-runtime-mcp-light");

  // --- Narrow window (~800px) ----------------------------------------------------
  await page.setViewportSize({ width: 800, height: 900 });
  await page.getByTitle("Chat", { exact: true }).click();
  await expect(page.locator(".answer-card")).toHaveCount(2, { timeout: BACKEND_WAIT });
  await page.waitForTimeout(600);
  await shot(page, "21-chat-narrow-800-light");

  await page.getByTitle("Settings", { exact: true }).click();
  await page
    .getByRole("button", { name: "配置状态", exact: true })
    .click();
  await expect(
    page.locator("h1", { hasText: "配置状态" }),
  ).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "22-settings-narrow-800-light");

  // --- No uncaught page errors anywhere in the tour.
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
});
