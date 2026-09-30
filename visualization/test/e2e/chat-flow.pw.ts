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
  return JSON.parse(readFileSync(connectionFile, "utf-8")) as BackendConnection;
}

const BACKEND_WAIT = 30_000;

test("F1-D 最小真实交互流程：提交 → 问题 → 回复 → 完成 → Session 恢复", async ({
  page,
}) => {
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
  await expect(page.getByText("Which option do you pick?")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await expect(page.locator('input[type="radio"]')).toHaveCount(2);
  await page.locator("label", { hasText: "Option B" }).click();
  await page.getByPlaceholder("Comment (optional)…").fill(commentText);
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

  // d. Session recovery: reload → day list → open the finished ask turn.
  await page.reload();
  await expect(page.getByText("Today's conversations")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
  await expect(page.locator("button", { hasText: plainText })).toHaveCount(1);
  await expect(page.locator("button", { hasText: askText })).toHaveCount(1);
  await page.locator("button", { hasText: askText }).click();
  await expect(page.getByText("Read-only history")).toBeVisible({
    timeout: BACKEND_WAIT,
  });
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
  await expect(page.locator(".answer-card")).toHaveCount(1);

  // e. No uncaught page errors anywhere in the flow.
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
});
