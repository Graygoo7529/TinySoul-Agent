import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ save: vi.fn(), invoke: vi.fn(), isTauriShell: vi.fn(), downloadJson: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: mocks.save }));
vi.mock("../../app/discovery", () => ({ isTauriShell: mocks.isTauriShell }));
vi.mock("../../utils/download", () => ({ downloadJson: mocks.downloadJson }));

import { buildTraceExport } from "./export";
import { saveTraceExport } from "./exportArchive";

const bundle = buildTraceExport("20261012/5", "2026-10-12", {
  events: [], through: 1, truncated: false, instanceId: "instance-1",
});

describe("saveTraceExport", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.isTauriShell.mockReturnValue(true);
  });

  it("opens a ZIP save dialog and sends the complete bundle to the archive writer", async () => {
    mocks.save.mockResolvedValue("B:/exports/turn.zip");
    mocks.invoke.mockResolvedValue("B:/exports/turn.zip");
    await expect(saveTraceExport(bundle)).resolves.toEqual({ status: "saved", path: "B:/exports/turn.zip" });
    expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({
      defaultPath: `${bundle.root}.zip`, filters: [{ name: "ZIP archive", extensions: ["zip"] }],
    }));
    expect(mocks.invoke).toHaveBeenCalledWith("write_export_archive", {
      archivePath: "B:/exports/turn.zip", files: bundle.files,
    });
    expect(bundle.files.some((entry) => entry.path === `${bundle.root}/turn.md`)).toBe(true);
  });

  it("does not write after cancellation and does not hide archive failures", async () => {
    mocks.save.mockResolvedValue(null);
    await expect(saveTraceExport(bundle)).resolves.toEqual({ status: "cancelled" });
    expect(mocks.invoke).not.toHaveBeenCalled();
    mocks.save.mockResolvedValue("B:/exports/turn.zip");
    mocks.invoke.mockRejectedValue(new Error("Cannot write export archive"));
    await expect(saveTraceExport(bundle)).rejects.toThrow("Cannot write export archive");
  });

  it("keeps the narrative and package paths in the browser fallback", async () => {
    mocks.isTauriShell.mockReturnValue(false);
    await expect(saveTraceExport(bundle)).resolves.toEqual({ status: "downloaded", filename: `${bundle.root}.json` });
    expect(mocks.downloadJson).toHaveBeenCalledWith(`${bundle.root}.json`, {
      manifest: bundle.manifest, index: bundle.index, files: bundle.files,
    });
    expect(mocks.save).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });
});
