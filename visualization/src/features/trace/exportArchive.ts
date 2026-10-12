import { invoke } from "@tauri-apps/api/core";
import { save } from "@tauri-apps/plugin-dialog";

import { isTauriShell } from "../../app/discovery";
import { downloadJson } from "../../utils/download";
import type { TraceExportBundle } from "./export";

export type TraceExportResult =
  | { status: "cancelled" }
  | { status: "downloaded"; filename: string }
  | { status: "saved"; path: string };

function archiveFilename(root: string): string {
  return `${root}.zip`;
}

/** Save one already-built trace bundle without adding business semantics. */
export async function saveTraceExport(bundle: TraceExportBundle): Promise<TraceExportResult> {
  const filename = archiveFilename(bundle.root);
  if (!isTauriShell()) {
    downloadJson(`${bundle.root}.json`, {
      manifest: bundle.manifest,
      index: bundle.index,
      files: bundle.files,
    });
    return { status: "downloaded", filename: `${bundle.root}.json` };
  }
  const archivePath = await save({
    title: "Export turn trace",
    defaultPath: filename,
    filters: [{ name: "ZIP archive", extensions: ["zip"] }],
  });
  if (archivePath === null) return { status: "cancelled" };
  const path = await invoke<string>("write_export_archive", {
    archivePath,
    files: bundle.files,
  });
  return { status: "saved", path };
}

