/**
 * Authenticated blob download (plan §10): the endpoint requires a Bearer
 * header, so downloads fetch the bytes through the transport and hand a
 * short-lived Object URL to an anchor — never the endpoint URL directly.
 */

import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";

export async function downloadWorkspaceBlob(
  link: string,
  day: string | null,
  filename: string,
): Promise<void> {
  const clients = useConnectionStore.getState().clients;
  if (clients === null) {
    useAppStore.getState().pushToast("error", "Not connected to a backend.");
    return;
  }
  try {
    const response = await clients.workspace.readBlob({
      link,
      day: day ?? undefined,
    });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = "noopener";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  } catch (error) {
    useAppStore
      .getState()
      .pushToast(
        "error",
        `Download failed: ${error instanceof Error ? error.message : String(error)}`,
      );
  }
}
