/**
 * F1-D e2e backend lifecycle (global setup/teardown for playwright.config.ts).
 *
 * Starts the real TinySoul backend harness (backend_server.py: real Agent +
 * Endpoint, scripted model) on an OS-assigned loopback port, waits for its
 * ready file, and publishes the connection target for the specs at
 * <repo>/.local-test/e2e-backend/connection.json (repo-level scratch tree,
 * outside the vite watch root). The project directory is recreated per run so
 * the Session day list starts empty.
 *
 * Python resolution order: $TINYSOUL_PYTHON, then $CONDA_PREFIX/python.exe
 * (an activated conda env), then "python" on PATH.
 */

import { spawn, type ChildProcess } from "node:child_process";
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const BACKEND_TOKEN = "e2e-playwright-token-0123456789abcdef012345";

const here = path.dirname(fileURLToPath(import.meta.url));
const visualizationRoot = path.resolve(here, "../..");
const repoRoot = path.resolve(visualizationRoot, "..");
// Keep the backend project outside the vite root: the dev server watches
// visualization/ and its transient read handles break the initializer's
// staging-directory rename on Windows.
const runDir = path.join(repoRoot, ".local-test", "e2e-backend");
const readyFile = path.join(runDir, "ready.json");
const connectionFile = path.join(runDir, "connection.json");
const pidFile = path.join(runDir, "backend.pid");
const logFile = path.join(runDir, "backend.log");
const projectDir = path.join(runDir, "project");
const harnessScript = path.join(here, "backend_server.py");

const READY_TIMEOUT_MS = 180_000;

let backend: ChildProcess | null = null;

function resolvePython(): string {
  const fromEnv = process.env.TINYSOUL_PYTHON?.trim();
  if (fromEnv) return fromEnv;
  const condaPrefix = process.env.CONDA_PREFIX?.trim();
  if (condaPrefix) {
    const candidate = path.join(condaPrefix, "python.exe");
    if (existsSync(candidate)) return candidate;
  }
  return "python";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  rmSync(runDir, { recursive: true, force: true });
  // Only the run dir is created here; the harness creates the project dir so
  // the initializer installs onto a fresh path (Windows replace semantics).
  mkdirSync(runDir, { recursive: true });
  const log = createWriteStream(logFile);
  const python = resolvePython();
  backend = spawn(
    python,
    [
      harnessScript,
      "--port",
      "0",
      "--token",
      BACKEND_TOKEN,
      "--project-dir",
      projectDir,
      "--ready-file",
      readyFile,
    ],
    { cwd: repoRoot, stdio: ["ignore", "pipe", "pipe"] },
  );
  backend.stdout?.pipe(log);
  backend.stderr?.pipe(log);
  writeFileSync(pidFile, String(backend.pid ?? ""), "utf-8");

  let exited = false;
  backend.once("exit", () => {
    exited = true;
  });
  const deadline = Date.now() + READY_TIMEOUT_MS;
  try {
    for (;;) {
      if (exited) {
        throw new Error(
          `e2e backend exited before ready; see ${logFile} (python: ${python})`,
        );
      }
      if (existsSync(readyFile)) {
        const ready = JSON.parse(readFileSync(readyFile, "utf-8")) as {
          port?: unknown;
        };
        if (typeof ready.port === "number" && ready.port > 0) {
          writeFileSync(
            connectionFile,
            JSON.stringify({
              address: `127.0.0.1:${ready.port}`,
              token: BACKEND_TOKEN,
            }),
            "utf-8",
          );
          console.log(
            `[e2e backend] serving at 127.0.0.1:${ready.port} (log: ${logFile})`,
          );
          return globalTeardown;
        }
      }
      if (Date.now() > deadline) {
        throw new Error(
          `e2e backend did not become ready within ${READY_TIMEOUT_MS}ms; see ${logFile} (python: ${python})`,
        );
      }
      await sleep(250);
    }
  } catch (error) {
    await globalTeardown();
    throw error;
  }
}

async function globalTeardown(): Promise<void> {
  const child = backend;
  backend = null;
  if (child && child.exitCode === null && !child.killed) {
    child.kill();
  } else if (!child && existsSync(pidFile)) {
    // Defensive fallback if setup/teardown ever run in separate processes.
    const pid = Number(readFileSync(pidFile, "utf-8"));
    if (Number.isInteger(pid) && pid > 0) {
      try {
        process.kill(pid);
      } catch {
        // already gone
      }
    }
  }
}
