/**
 * Fallback viewer for non-text workspace resources.
 *
 * Images are loaded via the authenticated blob endpoint; everything else shows
 * metadata and a future download action.
 */

import { useEffect, useState } from "react";
import { ImageIcon, File, Download } from "lucide-react";

import { useAppStore } from "../store/appStore";
import type { WorkspaceResourceRecord } from "../types";
import { formatSize, shorten } from "../utils/format";

interface BinaryPreviewProps {
  resource: WorkspaceResourceRecord;
}

export function BinaryPreview({ resource }: BinaryPreviewProps) {
  const client = useAppStore((state) => state.client);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!client || !resource.media_type.startsWith("image/")) return;
    let objectUrl: string | null = null;
    const load = async () => {
      try {
        const { blob } = await client.readWorkspaceBlob(resource.link);
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    void load();
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [client, resource.link, resource.media_type]);

  const isImage = resource.media_type.startsWith("image/");

  return (
    <div className="binary-preview panel h-full">
      <div className="panel-header">
        <span className="flex items-center gap-2">
          {isImage ? <ImageIcon size={14} /> : <File size={14} />}
          {resource.link}
        </span>
      </div>
      <div className="panel-body flex flex-col items-center justify-center gap-4">
        {isImage ? (
          url ? (
            <img
              src={url}
              alt={resource.link}
              style={{ maxWidth: "100%", maxHeight: "70%", borderRadius: "var(--radius-md)" }}
            />
          ) : error ? (
            <div className="text-danger text-sm">{error}</div>
          ) : (
            <div className="text-muted">Loading preview…</div>
          )
        ) : (
          <div className="empty-state-icon">
            <File size={48} />
          </div>
        )}
        <div className="text-sm text-muted text-center">
          <div className="font-semibold">{resource.media_type}</div>
          <div>{formatSize(resource.size)}</div>
          <div className="text-tertiary" title={resource.digest}>
            {resource.digest ? shorten(resource.digest) : "no digest"}
          </div>
        </div>
        {url && (
          <a
            href={url}
            download={resource.relative_path.split("/").pop() || resource.link}
            className="btn btn-sm btn-primary"
          >
            <Download size={12} />
            Download
          </a>
        )}
      </div>
    </div>
  );
}
