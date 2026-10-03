import { expect, test } from "playwright/test";
import { writeFile } from "node:fs/promises";
import type { ActivityPresentation, ActivityStep } from "../../src/features/chat/presentation";

test("live trail inserts above stable plan/result cards and clips their bottom edge", async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1000, height: 850 });
  await page.goto("/");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const report = await page.evaluate(async () => {
    // Mount the production component with real Motion/CSS. Only its semantic
    // feed is controlled, so frame measurements cover actual browser layout.
    const reactPath = "/node_modules/.vite/deps/react.js";
    const domPath = "/node_modules/.vite/deps/react-dom_client.js";
    const componentPath = "/src/features/chat/LiveStatus.tsx";
    const { default: { createElement } } = await import(reactPath) as { default: typeof import("react") };
    const { default: { createRoot } } = await import(domPath) as { default: typeof import("react-dom/client") };
    const { LiveStatus } = await import(componentPath) as typeof import("../../src/features/chat/LiveStatus");
    document.querySelector<HTMLElement>("#root")!.style.display = "none";
    const mount = document.createElement("div");
    mount.style.cssText = "width:620px;margin:30px auto";
    document.body.append(mount);
    const root = createRoot(mount);
    const trail: ActivityStep[] = [];
    const startedAt = new Date().toISOString();
    let headline: ActivityPresentation["headline"] = { phase: "phase3", label: "Executing actions…" };
    const render = () => {
      const activity: ActivityPresentation = {
        headline, trail: [...trail],
        thinking: { current: "", history: [], expanded: false }, working: { todos: [], milestones: [] },
        timing: { startedAt, elapsedMs: 0 }, incomplete: false,
      };
      root.render(createElement(LiveStatus, { epoch: 0, turnId: "motion-check", day: null, activity }));
    };
    const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
    type Row = { id: string; y: number; height: number };
    let previous: Row[] = [];
    let frames = 0;
    let halfCards = 0;
    let maxScroll = 0;
    const reversals: Row[] = [], shrinking: Row[] = [], changingOld: Row[] = [], visibleRemovals: Row[] = [];
    const appeared = new Map<string, number>();
    const partialReveals = new Set<string>();
    const sample = () => {
      const viewport = mount.querySelector<HTMLElement>(".steps-viewport");
      if (viewport) {
        frames++;
        const rect = viewport.getBoundingClientRect();
        maxScroll = Math.max(maxScroll, viewport.scrollTop);
        const rows = [...viewport.querySelectorAll<HTMLElement>("[data-activity-step]")].map((node): Row => {
          const box = node.getBoundingClientRect();
          return { id: node.dataset.activityStep!, y: box.top - rect.top, height: box.height };
        });
        for (const row of rows) {
          if (!appeared.has(row.id)) appeared.set(row.id, performance.now());
          const age = performance.now() - appeared.get(row.id)!;
          const prior = previous.find((entry) => entry.id === row.id);
          const visible = row.y < rect.height && row.y + row.height > 0;
          if (visible && prior) {
            if (row.y < prior.y - 0.8) reversals.push(row);
            if (row.height < prior.height - 0.8) shrinking.push(row);
            if (age > 1000 && Math.abs(row.height - prior.height) > 0.8) changingOld.push(row);
          }
          if (row.y > 0 && row.y < rect.height - 10 && row.y + row.height > rect.height + 10) halfCards++;
        }
        for (const row of previous) if (row.y < rect.height && !rows.some((entry) => entry.id === row.id)) visibleRemovals.push(row);
        for (const gist of viewport.querySelectorAll<HTMLElement>('[data-activity-gist="result"]')) {
          const height = gist.getBoundingClientRect().height;
          if (height > 2 && height < gist.scrollHeight - 2) partialReveals.add(gist.closest<HTMLElement>("[data-activity-step]")!.dataset.activityStep!);
        }
        previous = rows;
      }
      frame = requestAnimationFrame(sample);
    };
    let frame = requestAnimationFrame(sample);
    render();
    const push = (i: number) => {
      const result = i % 2 === 1;
      const type = result ? "action_result" : "action_plan";
      trail.push({ id: `row-${i}`, type, timestamp: startedAt, cycleId: "c", phase: result ? "phase3" : "phase2", autoExpandGist: true,
        content: { type, glimpse: { actionId: "execution.run_shell", callId: `call-${i}`, domain: "execution", stage: result ? "result" : "plan",
          params: { command: `echo resource ${i}` }, executionState: result ? "executed" : "planned",
          ...(result ? { payload: { stdout: `resource ${i}\nchecked\nready`, stderr: "", exit_code: 0 }, result: { status: "success", preview: "Resource checked" } } : {}),
        } } });
      render();
    };
    for (let i = 0; i < 18; i++) { push(i); await pause(1300); }
    // Updating execution badges never replaces the older plan's body.
    for (const item of trail) if (item.content.type === "action_plan") item.content.glimpse.executionState = "executed";
    render();
    // Fewer than ten pending steps: only a new reasoning anchor can trigger
    // the fast drain. The headline and thinking share the statement beat.
    for (let i = 18; i < 24; i++) push(i);
    headline = { phase: "phase1", label: "Maintaining context and selecting domains…" };
    trail.push({ id: "thought-anchor", type: "thinking", timestamp: startedAt, cycleId: "c2", phase: "phase1", autoExpandGist: true,
      content: { type: "thinking", text: "Review the results before proceeding.", source: "reasoning" } });
    render();
    await pause(4500);
    const releaseGaps = (ids: string[]) => ids.slice(1).map((id, i) => appeared.get(id)! - appeared.get(ids[i])!);
    const thoughtDrain = releaseGaps(["row-20", "row-21", "row-22", "row-23", "thought-anchor"]);
    // A large backlog triggers its own bounded drain without another thought.
    for (let i = 24; i < 42; i++) push(i);
    await pause(11000);
    cancelAnimationFrame(frame);
    const backlogDrain = releaseGaps(["row-24", "row-25", "row-26", "row-27", "row-28", "row-29"]);
    return { frames, halfCards, maxScroll, partialReveals: [...partialReveals], thoughtDrain, backlogDrain,
      reversals, shrinking, changingOld, visibleRemovals };
  });
  const geometryPath = testInfo.outputPath("trail-geometry.json");
  await writeFile(geometryPath, JSON.stringify(report, null, 2));
  await testInfo.attach("trail-geometry.json", { path: geometryPath, contentType: "application/json" });
  await page.screenshot({ path: testInfo.outputPath("trail-bottom-clip.png") });
  expect(report.frames).toBeGreaterThan(100);
  expect(report.partialReveals.length).toBeGreaterThan(0);
  expect(report.halfCards).toBeGreaterThan(0);
  expect(report.maxScroll).toBe(0);
  for (const gaps of [report.thoughtDrain, report.backlogDrain]) {
    expect(gaps.every((ms) => Number.isFinite(ms) && ms > 0 && ms < 600)).toBe(true);
  }
  expect(report.reversals).toEqual([]);
  expect(report.shrinking).toEqual([]);
  expect(report.changingOld).toEqual([]);
  expect(report.visibleRemovals).toEqual([]);
  expect(errors).toEqual([]);
});
