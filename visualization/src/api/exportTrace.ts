/**
 * Turn trace export.
 *
 * In the Tauri shell the user picks a directory and the Rust side writes the
 * bundle (turn.json + trace.md + one JSON per LLM call under per-cycle
 * subdirectories). In a plain browser (web dev mode) there is no filesystem
 * access, so the structured JSON falls back to a browser download.
 */

import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type { ChatTurn } from "../derive/model";
import {
  buildTurnExportBundle,
  downloadTextFile,
  turnTraceFilename,
  turnTraceToJson,
} from "../derive/export";
import { isTauriShell } from "./connection";

export interface ExportOutcome {
  kind: "written" | "downloaded" | "cancelled";
  location?: string;
}

export async function exportTurnTrace(turn: ChatTurn): Promise<ExportOutcome> {
  const bundle = buildTurnExportBundle(turn);
  if (isTauriShell()) {
    const picked = await open({
      directory: true,
      multiple: false,
      title: "Choose where to export the turn trace",
    });
    if (!picked) return { kind: "cancelled" };
    const root = await invoke<string>("write_export_files", {
      baseDir: picked,
      files: bundle.files.map((f) => ({
        path: `${bundle.dirName}/${f.path}`,
        contents: f.contents,
      })),
    });
    return { kind: "written", location: root };
  }
  // Browser fallback: single structured JSON download.
  downloadTextFile(
    turnTraceFilename(turn, "json"),
    turnTraceToJson(turn),
    "application/json",
  );
  return { kind: "downloaded", location: "browser downloads" };
}
