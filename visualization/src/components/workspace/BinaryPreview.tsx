import { useEffect, useState } from "react";
import { Download, FileQuestion } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { formatSize, shorten } from "../../utils/format";
import type { WorkspaceResourceRecord } from "../../types";
import { EmptyState } from "../ui/EmptyState";

/** Preview for non-text workspace resources (images render, others show metadata). */
export function BinaryPreview({ resource }: { resource: WorkspaceResourceRecord }) {
  const client = useAppStore((s) => s.client);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isImage = resource.media_type.startsWith("image/");

  useEffect(() => {
    setObjectUrl(null);
    setError(null);
    if (!client || !isImage) return;
    let revoked: string | null = null;
    client
      .readWorkspaceBlob(resource.link)
      .then(({ blob }) => {
        revoked = URL.createObjectURL(blob);
        setObjectUrl(revoked);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [client, resource.link, isImage]);

  const download = async () => {
    if (!client) return;
    try {
      const { blob } = await client.readWorkspaceBlob(resource.link);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = resource.relative_path.split("/").pop() ?? "download";
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      {isImage && objectUrl ? (
        <img
          src={objectUrl}
          alt={resource.relative_path}
          className="max-h-[70%] max-w-full rounded-lg border border-line object-contain"
        />
      ) : (
        <EmptyState
          icon={<FileQuestion size={28} />}
          title={isImage ? "Loading image…" : "Binary resource"}
          description={`${resource.media_type} · ${formatSize(resource.size)} · digest ${shorten(resource.digest ?? "", 16)}`}
        />
      )}
      {error && <div className="text-[12px] text-danger">{error}</div>}
      <button
        onClick={() => void download()}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-bg-elev px-3 py-1.5 text-[13px] text-fg hover:bg-hover"
      >
        <Download size={13} />
        Download
      </button>
    </div>
  );
}
