import { useEffect, useState } from "react";
import type { PresentationAsset } from "../../../api/v2/presentation";
import { useConnectionStore } from "../../../store/connectionStore";
import { settingsText } from "../i18n";
import { usePresentationAssetUrl } from "../presentationAssets";

const PREVIEW_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp"]);

export function PresentationAssets() {
  const [open, setOpen] = useState(false);
  return <details className="rounded-lg border border-line bg-bg-elev p-4" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-medium">{settingsText("Project shared assets")}</summary>
    {open && <AssetList />}
  </details>;
}

function AssetList() {
  const clients = useConnectionStore((s) => s.clients);
  const connected = useConnectionStore((s) => s.phase === "connected" && !s.unreachable);
  const epoch = useConnectionStore((s) => s.epoch);
  const [attempt, setAttempt] = useState(0);
  const [items, setItems] = useState<PresentationAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<PresentationAsset | null>(null);
  const blob = usePresentationAssetUrl(selected?.path ?? null);

  useEffect(() => {
    setItems([]);
    setSelected(null);
    setError(null);
    if (!clients || !connected) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    clients.presentation.assets({ signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) setItems(result.items);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [clients, connected, epoch, attempt]);

  return <div className="mt-3 flex flex-col gap-3 text-xs">
    <div className="flex items-center gap-3 text-fg-muted">
      <span>{settingsText("Files in this project's presentation/assets directory.")}</span>
      <button type="button" className="text-accent disabled:opacity-40" disabled={!connected || loading} onClick={() => setAttempt((value) => value + 1)}>{settingsText("Refresh")}</button>
    </div>
    {!connected && <p>{settingsText("Connect to read project assets.")}</p>}
    {loading && <p>{settingsText("Loading assets…")}</p>}
    {error && <p role="alert" className="text-danger">{error}</p>}
    {connected && !loading && !error && items.length === 0 && <p className="text-fg-muted">{settingsText("No shared assets. Place files in presentation/assets and refresh.")}</p>}
    <ul className="flex flex-col gap-1">
      {items.map((asset) => <li key={asset.path}>
        <button type="button" className={`flex w-full items-center justify-between gap-3 rounded px-2 py-2 text-left hover:bg-hover ${selected?.path === asset.path ? "bg-active" : ""}`}
          onClick={() => setSelected(asset)}>
          <span className="break-all">{asset.path}</span><span className="shrink-0 text-fg-muted">{asset.size.toLocaleString()} B</span>
        </button>
      </li>)}
    </ul>
    {blob.loading && <p>{settingsText("Loading asset…")}</p>}
    {blob.error && <p role="alert" className="text-danger">{blob.error}</p>}
    {selected && blob.url && <div className="flex flex-col items-start gap-2 rounded border border-line p-3">
      {PREVIEW_TYPES.has(blob.mediaType ?? "") && <img className="max-h-64 max-w-full object-contain" src={blob.url} alt={selected.path} />}
      <a className="text-accent" href={blob.url} download={selected.path.split("/").pop()}>{settingsText("Download")}</a>
    </div>}
  </div>;
}
