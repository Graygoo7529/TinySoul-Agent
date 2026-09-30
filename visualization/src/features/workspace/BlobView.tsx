/**
 * Non-text workspace resources (plan §10/P06).
 *
 * Images embed through the authenticated blob client (Object URL). Every
 * other binary kind — documents, audio, video, unknown — shows its manifest
 * metadata plus a real download; the page never fakes playback of media it
 * cannot embed.
 */

import type { ReactElement } from "react";
import { AlertTriangle, Download, File as FileIcon, Loader2 } from "lucide-react";

import type { WorkspaceResourceRecord } from "../../api/v2/types";
import { Button } from "../../components/ui/Button";
import { useWorkspaceBlobUrl } from "../resources/blobUrl";
import { formatSize } from "../../utils/format";
import { downloadWorkspaceBlob } from "./download";

export function BlobView({
  link,
  day,
  record,
}: {
  /** Fragment-free `workspace:` link. */
  link: string;
  /** Archive binding; null reads the active day. */
  day: string | null;
  record: WorkspaceResourceRecord;
}): ReactElement {
  if (record.media_type.startsWith("image/")) {
    return <ImageBlob link={link} day={day} record={record} />;
  }
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4 rounded-xl border border-line bg-bg-elev px-5 py-5">
        <div className="flex items-center gap-3">
          <FileIcon size={22} className="shrink-0 text-fg-faint" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium" title={record.relative_path}>
              {record.relative_path}
            </div>
            <div className="text-[11px] text-fg-faint">{record.kind}</div>
          </div>
        </div>
        <dl className="space-y-1.5 text-[12px]">
          <MetadataRow label="Media type" value={record.media_type} />
          <MetadataRow label="Size" value={formatSize(record.size)} />
          {record.description !== "" && (
            <MetadataRow label="Description" value={record.description} />
          )}
        </dl>
        <div className="text-[11px] leading-4 text-fg-faint">
          This file type is not embedded in the page. Download it to open with
          a local application.
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void downloadWorkspaceBlob(link, day, fileName(record))}
        >
          <Download size={13} />
          Download
        </Button>
      </div>
    </div>
  );
}

function ImageBlob({
  link,
  day,
  record,
}: {
  link: string;
  day: string | null;
  record: WorkspaceResourceRecord;
}): ReactElement {
  const blob = useWorkspaceBlobUrl(link, day);
  if (blob.error !== null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="flex max-w-md items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
          <AlertTriangle size={13} className="shrink-0" />
          The image could not be read: {blob.error}
        </div>
      </div>
    );
  }
  if (blob.url === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-fg-faint">
        <Loader2 size={16} className="animate-spin-slow" />
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-line px-4 py-1.5 text-[11px] text-fg-faint">
        <span>{record.media_type}</span>
        <span>·</span>
        <span>{formatSize(record.size)}</span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="xs"
          onClick={() => void downloadWorkspaceBlob(link, day, fileName(record))}
        >
          <Download size={12} />
          Download
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
        <img
          src={blob.url}
          alt={record.relative_path}
          className="max-h-full max-w-full object-contain"
        />
      </div>
    </div>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 text-fg-faint">{label}</dt>
      <dd className="min-w-0 flex-1 break-words text-fg-muted">{value}</dd>
    </div>
  );
}

function fileName(record: WorkspaceResourceRecord): string {
  const path = record.relative_path;
  const slash = path.lastIndexOf("/");
  return slash < 0 ? path : path.slice(slash + 1);
}
