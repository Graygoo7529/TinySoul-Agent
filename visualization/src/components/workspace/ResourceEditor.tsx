import { useMemo, useState } from "react";
import { AlertTriangle, RotateCcw, Save } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { useWorkspace } from "../../hooks/useWorkspace";
import { formatSize, shorten } from "../../utils/format";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Tabs } from "../ui/Tabs";
import { Markdown } from "../markdown/Markdown";

/**
 * Text resource editor with a live Markdown preview. Writes go through the
 * Endpoint with revision/digest CAS; conflicts keep the user's draft and
 * offer explicit Overwrite / Reload resolution.
 */
export function ResourceEditor() {
  const openResource = useAppStore((s) => s.openResource);
  const conflict = useAppStore((s) => s.workspaceConflict);
  const updateDraft = useAppStore((s) => s.updateResourceDraft);
  const pushToast = useAppStore((s) => s.pushToast);
  const { saveText, readText } = useWorkspace();
  const [mode, setMode] = useState<"split" | "source" | "preview">("split");
  const [saving, setSaving] = useState(false);

  const words = useMemo(() => {
    if (!openResource) return 0;
    const trimmed = openResource.draft.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }, [openResource]);

  if (!openResource) return null;
  const { link, read, dirty, draft } = openResource;
  const isMarkdown = /\.(md|markdown)$/i.test(link);

  const save = async (overwrite: boolean) => {
    setSaving(true);
    try {
      await saveText(link, draft, overwrite, read.digest);
      if (!conflict) pushToast("success", `Saved ${link}`);
    } finally {
      setSaving(false);
    }
  };

  const reload = async () => {
    await readText(link);
    pushToast("info", "Reloaded the latest version; your draft was replaced.");
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* header */}
      <div className="flex items-center gap-2 border-b border-line bg-bg-elev px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">{link}</span>
        {dirty && <Badge tone="yellow">modified</Badge>}
        <span className="shrink-0 text-[10px] text-fg-faint">
          {words} words · {formatSize(new Blob([draft]).size)} · {shorten(read.digest, 10)}
        </span>
        {isMarkdown && (
          <Tabs
            items={[
              { value: "source", label: "Source" },
              { value: "split", label: "Split" },
              { value: "preview", label: "Preview" },
            ]}
            value={mode}
            onChange={setMode}
          />
        )}
        <Button
          variant="ghost"
          size="xs"
          disabled={!dirty}
          onClick={() => updateDraft(read.text)}
        >
          <RotateCcw size={12} />
          Discard
        </Button>
        <Button
          variant="primary"
          size="xs"
          loading={saving}
          disabled={!dirty}
          onClick={() => void save(false)}
        >
          <Save size={12} />
          Save
        </Button>
      </div>

      {/* conflict banner */}
      {conflict && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
          <AlertTriangle size={13} className="shrink-0" />
          <span className="min-w-0 flex-1">
            The resource changed on the backend while you were editing.
          </span>
          <Button size="xs" variant="outline" onClick={() => void save(true)}>
            Overwrite
          </Button>
          <Button size="xs" variant="outline" onClick={() => void reload()}>
            Reload
          </Button>
        </div>
      )}

      {/* body */}
      <div className="grid min-h-0 flex-1" style={{ gridTemplateColumns: mode === "split" ? "1fr 1fr" : "1fr" }}>
        {mode !== "preview" && (
          <textarea
            value={draft}
            onChange={(e) => updateDraft(e.target.value)}
            spellCheck={false}
            className={`h-full w-full resize-none bg-bg-elev p-4 font-mono text-[12.5px] leading-6 outline-none ${
              mode === "split" ? "border-r border-line" : ""
            }`}
          />
        )}
        {mode !== "source" && (
          <div className="h-full overflow-y-auto bg-bg-elev p-4">
            {isMarkdown ? (
              <Markdown>{draft}</Markdown>
            ) : (
              <pre className="font-mono text-[12.5px] leading-6 whitespace-pre-wrap">{draft}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
