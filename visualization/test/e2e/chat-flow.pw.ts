import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "playwright/test";

/**
 * F1-D exit criterion: the minimal real interaction flow against the real
 * Endpoint (backend_server.py harness — real Agent/owners/HTTP/WS, scripted
 * model). Nothing in the frontend or the transport is mocked.
 *
 * Flow: connect → send a plain message → echo answer → send an ask-trigger
 * message → live question card → choice reply with comment → read-only
 * answered card → final answer → reload the page → the finished turns are
 * recovered from the Session owner with the right identities.
 */

const here = path.dirname(fileURLToPath(import.meta.url));
const connectionFile = path.resolve(
  here,
  "../../../.local-test/e2e-backend/connection.json",
);

interface BackendConnection {
  address: string;
  token: string;
}

function backendConnection(): BackendConnection {
  return JSON.parse(readFileSync(process.env.TINYSOUL_E2E_CONNECTION ?? connectionFile, "utf-8")) as BackendConnection;
}

const BACKEND_WAIT = 30_000;

test("F1-D 最小真实交互流程：提交 → 问题 → 回复 → 完成 → Session 恢复", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { address, token } = backendConnection();
  const runId = Date.now().toString(36);
  const plainText = `e2e-plain hello ${runId}`;
  const askText = `e2e-ask pick one ${runId}`;
  const commentText = `e2e-reply-comment ${runId}`;
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(String(err)));

  // a. Connect through the real form (health + status handshake + WS stream).
  await page.goto("/");
  await page.getByPlaceholder("127.0.0.1:1430").fill(address);
  await page.locator('input[type="password"]').fill(token);
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Start a conversation")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await expect(page.getByTitle("Workspace")).toBeEnabled();

  // b. Plain message: echo answer, no duplicated rows after convergence.
  const composer = page.getByPlaceholder("Message TinySoul…");
  await composer.fill(plainText);
  await composer.press("Enter");
  await expect(
    page.locator(".bubble-user", { hasText: plainText }),
  ).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(
    page.locator(".answer-card", { hasText: `You said: ${plainText}.` }),
  ).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(page.locator(".answer-card")).toHaveCount(1);

  // c. Ask flow: live question card → choice + comment → answered read-only.
  await expect(page.getByPlaceholder("Message TinySoul…")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await composer.fill(askText);
  await composer.press("Enter");
  // Sample geometry while the new Turn lands; a final-position assertion
  // alone cannot distinguish the baseline glide from an immediate jump.
  const positions = await page.evaluate(async () => {
    const samples: number[] = [];
    const start = performance.now();
    const first = document.querySelectorAll("[data-turn-root]").length;
    while (performance.now() - start < 1800) {
      const turns = document.querySelectorAll("[data-turn-root]");
      const scroll = document.querySelector(".chat-grid");
      if (turns.length >= 2 && scroll) samples.push(turns[turns.length - 1].getBoundingClientRect().top - scroll.getBoundingClientRect().top);
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    }
    return { samples, first };
  });
  expect(positions.samples.length).toBeGreaterThan(3);
  expect(Math.max(...positions.samples) - Math.min(...positions.samples)).toBeGreaterThan(15);
  expect(positions.samples.at(-1)).toBeCloseTo(20, 0);
  await expect(page.getByText("Which option do you pick?")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await expect(page.locator('input[type="radio"]')).toHaveCount(2);
  // Real model-boundary observations feed the restored thinking trail.
  await expect(page.locator(".thinking-slate").first()).toBeAttached();
  await expect(page.locator(".live-border")).toContainText("Waiting for you");
  const allSteps = page.getByRole("button", { name: /earlier steps|Show all steps/ });
  if (await allSteps.count()) await allSteps.click();
  await expect(page.locator(".steps-viewport")).toContainText("home:skills@review", { timeout: BACKEND_WAIT });
  await expect(page.locator('[data-activity-gist="result"]')).toContainText("baseline-output-ready", { timeout: BACKEND_WAIT });
  const turnNode = await page.locator("[data-turn-root]").last().elementHandle();
  const activityNode = await page.locator(".live-border").elementHandle();
  await page.screenshot({ path: testInfo.outputPath("chat-waiting.png") });
  await page.getByRole("button", { name: "Context", exact: true }).click();
  const inspector = page.getByRole("dialog");
  await expect(inspector.getByRole("button", { name: "当前 Context", exact: true })).toBeVisible();
  for (const tab of ["Session map", "已加载 Home", "已加载 Memory", "当前 Context"]) {
    await inspector.getByRole("button", { name: tab, exact: true }).click();
    await expect(inspector.locator(".animate-spin-slow:visible")).toHaveCount(0);
    if (tab === "已加载 Home") {
      await expect(inspector.getByText("Keep the original visual rhythm and verify real owner facts.")).toBeVisible();
      await inspector.locator("article", { hasText: "Review baseline" }).getByRole("button", { name: "展开全文" }).click();
    }
    if (tab === "已加载 Memory") await expect(inspector.locator("article")).toContainText("memory:current");
  }
  await inspector.getByRole("button", { name: "已加载 Home", exact: true }).click();
  await expect(inspector.locator("article", { hasText: "Review baseline" }).getByRole("button", { name: "收起", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("context-tabs.png") });
  await inspector.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Details", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Turn Trace", exact: true })).toBeVisible();
  await page.getByTitle("View the LLM message stack", { exact: true }).first().click();
  await expect(page.getByRole("dialog")).toHaveCount(2);
  await expect(page.locator(".inspector-adjacent")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Model task", exact: true })).toBeVisible();
  await expect(page.locator(".inspector-adjacent")).toHaveCSS("opacity", "1");
  await expect(page.locator(".inspector-adjacent").getByText(/TinySoul provider-neutral request/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("trace-model-context.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.locator("label", { hasText: "Option B" }).click();
  await page.getByPlaceholder("Comment (optional)…").fill(commentText);
  const completionFrames = page.evaluate(async () => {
    const turn = [...document.querySelectorAll("[data-turn-root]")].at(-1)!;
    const body = turn.querySelector<HTMLElement>("[data-live-body]")!;
    const samples: Array<{ height: number; answerOpacity: number; typing: boolean; settling: boolean }> = [];
    const start = performance.now();
    while (performance.now() - start < 6500) {
      const answer = turn.querySelector<HTMLElement>(".answer-card");
      samples.push({ height: body.getBoundingClientRect().height, answerOpacity: answer ? Number(getComputedStyle(answer).opacity) : 0,
        typing: answer?.classList.contains("answer-streaming") ?? false, settling: answer?.classList.contains("answer-settling") ?? false });
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    }
    return samples;
  });
  await page.getByRole("button", { name: "Reply" }).click();

  // The formal reply converges the card into its read-only answered state.
  await expect(page.locator('input[type="radio"]')).toHaveCount(0, {
    timeout: BACKEND_WAIT,
  });
  await expect(page.getByText("answered", { exact: true })).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await expect(
    page.locator('[class*="border-accent/50"]', { hasText: "Option B" }),
  ).toBeVisible();
  await expect(
    page.locator(".bubble-user", { hasText: commentText }),
  ).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(
    page.locator(".answer-card", {
      hasText: "You picked Option B (opt_b).",
    }),
  ).toHaveCount(1, { timeout: BACKEND_WAIT });
  await expect(
    page.locator(".answer-card", { hasText: commentText }),
  ).toHaveCount(1);
  expect(await turnNode?.evaluate((node) => node.isConnected)).toBe(true);
  expect(await activityNode?.evaluate((node) => node.isConnected)).toBe(true);
  const frames = await completionFrames;
  const initialHeight = frames[0].height;
  expect(frames.some((sample) => sample.height > 5 && sample.height < initialHeight - 20)).toBe(true);
  expect(frames.some((sample) => sample.height < 1 && sample.answerOpacity > 0.95 && sample.typing)).toBe(true);
  expect(frames.some((sample) => sample.settling)).toBe(true);
  await expect(page.locator(".answer-streaming")).toHaveCount(0, { timeout: BACKEND_WAIT });
  await expect(page.locator(".answer-settling")).toHaveCount(0, { timeout: BACKEND_WAIT });
  await page.getByRole("button", { name: "Context", exact: true }).click();
  await inspector.getByRole("button", { name: "已加载 Home", exact: true }).click();
  await expect(inspector.locator('[data-background-source="session"]')).toContainText("Keep the original visual rhythm and verify real owner facts.");
  await inspector.getByRole("button", { name: "Close", exact: true }).click();

  // d. Session recovery keeps both full conversations on the same day page.
  await page.reload();
  await expect(page.locator(".answer-card")).toHaveCount(2, {
    timeout: BACKEND_WAIT,
  });
  await expect(page.locator(".bubble-user", { hasText: plainText })).toHaveCount(1);
  await expect(page.getByPlaceholder("Message TinySoul…")).toBeEnabled();
  await expect(
    page.locator(".bubble-user", { hasText: askText }),
  ).toHaveCount(1);
  await expect(
    page.locator(".bubble-user", { hasText: commentText }),
  ).toHaveCount(1);
  await expect(page.getByText("Which option do you pick?")).toBeVisible();
  await expect(
    page.locator(".answer-card", { hasText: "You picked Option B (opt_b)." }),
  ).toHaveCount(1);
  await expect(page.locator(".answer-card")).toHaveCount(2);
  await page.screenshot({ path: testInfo.outputPath("chat-continuous.png") });
  await page.getByRole("button", { name: "Context", exact: true }).click();
  await inspector.getByRole("button", { name: "已加载 Home", exact: true }).click();
  await expect(inspector.locator('[data-background-source="session"]')).toContainText("Keep the original visual rhythm and verify real owner facts.");
  await page.screenshot({ path: testInfo.outputPath("context-completed.png") });
  await inspector.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByTitle("Settings", { exact: true }).click();
  await page.getByRole("button", { name: /LLM 模型/ }).first().click();
  await expect(page.getByText("模型能力", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("settings-models-zh.png") });

  // e. No uncaught page errors anywhere in the flow.
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
});
