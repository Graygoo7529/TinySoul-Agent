import { useEffect, useState } from "react";

export interface BlobObjectUrl {
  url: string | null;
  mediaType: string | null;
  loading: boolean;
  error: string | null;
}

/** Caller supplies a stable, authenticated read bound to its resource/connection. */
export function useBlobObjectUrl(read: ((signal: AbortSignal) => Promise<Response>) | null): BlobObjectUrl {
  const [state, setState] = useState<BlobObjectUrl>({ url: null, mediaType: null, loading: read !== null, error: null });
  useEffect(() => {
    if (!read) {
      setState({ url: null, mediaType: null, loading: false, error: null });
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState({ url: null, mediaType: null, loading: true, error: null });
    read(controller.signal).then(async (response) => {
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setState({ url: objectUrl, mediaType: response.headers.get("Content-Type"), loading: false, error: null });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setState({ url: null, mediaType: null, loading: false, error: error instanceof Error ? error.message : String(error) });
    });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [read]);
  return state;
}
