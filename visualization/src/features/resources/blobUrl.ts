/**
 * Authenticated Workspace blob reads as Object URLs (plan §10).
 *
 * The endpoint requires a Bearer header, so media never points <img>/<video>
 * at the endpoint URL directly: the bytes come through the transport, become
 * a Blob and then an Object URL that this hook revokes on invalidation or
 * unmount.
 */

import { useEffect, useState } from "react";

import { useConnectionStore } from "../../store/connectionStore";

export interface BlobObjectUrl {
  url: string | null;
  /** Content-Type reported by the endpoint, when known. */
  mediaType: string | null;
  loading: boolean;
  error: string | null;
}

/**
 * Fetch one workspace blob (whole read; Range stays a transport capability —
 * partial media playback is not claimed). `link` is the fragment-free
 * workspace link, `day` the archive binding (null = active day).
 */
export function useWorkspaceBlobUrl(
  link: string | null,
  day: string | null,
): BlobObjectUrl {
  const epoch = useConnectionStore((s) => s.epoch);
  const [state, setState] = useState<BlobObjectUrl>({
    url: null,
    mediaType: null,
    loading: link !== null,
    error: null,
  });

  useEffect(() => {
    if (link === null) {
      setState({ url: null, mediaType: null, loading: false, error: null });
      return;
    }
    const clients = useConnectionStore.getState().clients;
    if (clients === null || useConnectionStore.getState().epoch !== epoch) {
      setState({
        url: null,
        mediaType: null,
        loading: false,
        error: "Not connected to a backend.",
      });
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState({ url: null, mediaType: null, loading: true, error: null });
    clients.workspace
      .readBlob({ link, day: day ?? undefined }, { signal: controller.signal })
      .then(async (response) => {
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setState({
          url: objectUrl,
          mediaType: response.headers.get("Content-Type"),
          loading: false,
          error: null,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          url: null,
          mediaType: null,
          loading: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return () => {
      controller.abort();
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl);
    };
  }, [epoch, link, day]);

  return state;
}
