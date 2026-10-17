import { useMemo } from "react";
import { useBlobObjectUrl } from "../../hooks/useBlobObjectUrl";
import { useConnectionStore } from "../../store/connectionStore";

export function usePresentationAssetUrl(path: string | null) {
  const clients = useConnectionStore((s) => s.clients);
  const epoch = useConnectionStore((s) => s.epoch);
  const read = useMemo(() => path && clients
    ? (signal: AbortSignal) => clients.presentation.readBlob(path, { signal })
    : null, [clients, epoch, path]);
  return useBlobObjectUrl(read);
}
