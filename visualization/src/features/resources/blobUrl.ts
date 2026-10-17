/** Workspace addressing over the shared authenticated Blob lifecycle. */
import { useMemo } from "react";
import { useBlobObjectUrl } from "../../hooks/useBlobObjectUrl";
import { useConnectionStore } from "../../store/connectionStore";

export function useWorkspaceBlobUrl(resourceRef: string | null, day: string | null) {
  const clients = useConnectionStore((s) => s.clients);
  const epoch = useConnectionStore((s) => s.epoch);
  const read = useMemo(() => resourceRef && clients
    ? (signal: AbortSignal) => clients.workspace.readBlob({ ref: resourceRef, day: day ?? undefined }, { signal })
    : null, [clients, epoch, resourceRef, day]);
  return useBlobObjectUrl(read);
}
