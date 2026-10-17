/**
 * The Composer run-plan quick entry (implementation plan §5.2).
 *
 * Lists every plan with its current declaration match and stored content.
 * Settings and chat share the same comparison and draft confirmation flow.
 * Applying a plan and starting a turn remain separate actions.
 */

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Layers,
  Loader2,
  Settings2,
} from "lucide-react";

import type { Preset, PresetSummary } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { settingsText } from "../settings/i18n";
import { ensureConfigLoaded } from "../settings/applyController";
import {
  activationBlocker,
  useConfigDraftStore,
} from "../settings/draft/store";
import { useSettingsUiStore } from "../settings/uiStore";
import { usePresetApplyFlow } from "../settings/presets/PresetApplyDialog";
import {
  decodePresetDefinition,
  parseValidationIssues,
} from "../settings/presets/presetsModel";
import { PresetContent } from "../settings/presets/PresetChanges";

export function PresetEntry() {
  const phase = useConnectionStore((s) => s.phase);
  const clients = useConnectionStore((s) => s.clients);
  const connected = phase === "connected" && clients !== null;
  const loadPhase = useConfigDraftStore((s) => s.loadPhase);
  const loadError = useConfigDraftStore((s) => s.loadError);
  const presets = useConfigDraftStore((s) => s.presets);
  const [open, setOpen] = useState(false);

  // Lazy config definitions shared with the settings pages; one load per
  // connection (see ensureConfigLoaded).
  useEffect(() => {
    if (clients !== null) ensureConfigLoaded(clients);
  }, [clients]);

  if (!connected) return null;

  return (
    <div data-slot="preset-entry" className="relative">
      <button
        type="button"
        title="运行方案"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-bg-elev px-2.5 text-[11.5px] font-medium text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
      >
        {loadPhase === "loading" && presets === null ? (
          <Loader2 size={12} className="animate-spin-slow" />
        ) : (
          <Layers size={12} />
        )}
        <span className="max-w-28 truncate">运行方案</span>
        <ChevronUp size={11} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
      </button>
      {open && (
        <PresetPopover
          presets={presets ?? []}
          loadError={loadError}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

function PresetPopover({
  presets,
  loadError,
  onClose,
}: {
  presets: PresetSummary[];
  loadError: string | null;
  onClose: () => void;
}) {
  const blocker = useConfigDraftStore(activationBlocker);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const { requestApply, confirmDialog, applying, previewing } = usePresetApplyFlow({
    onReview: () => goToSettings("overview"),
  });

  function goToSettings(page: "plans" | "overview" = "plans") {
    useAppStore.getState().setActiveTab("settings");
    useSettingsUiStore.getState().navigateTo(page);
    onClose();
  }

  // Dismiss on Escape and on outside pointer-down.
  useEffect(() => {
    if (previewing) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    const onPointer = (event: MouseEvent) => {
      const root = rootRef.current?.parentElement;
      if (root !== null && root !== undefined && !root.contains(event.target as Node)) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointer);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointer);
    };
  }, [onClose, previewing]);

  return (
    <div
      ref={rootRef}
      className="absolute right-0 bottom-full z-(--z-drawer) mb-2 w-84 max-w-[calc(100vw-2rem)] rounded-xl border border-line bg-bg-elev shadow-pop"
    >
      <div className="flex items-center gap-2 border-b border-line px-3.5 py-2.5">
        <span className="min-w-0 flex-1 text-[12.5px] font-semibold">
          运行方案
        </span>
        <Button variant="ghost" size="xs" onClick={() => goToSettings("plans")}>
          <Settings2 size={12} /> 管理方案
        </Button>
      </div>

      {blocker !== null && (
        <div className="border-b border-line px-3.5 py-2 text-[11px] leading-4 text-fg-faint">
          暂时无法应用方案：{settingsText(blocker)}
        </div>
      )}
      {loadError !== null && (
        <div className="border-b border-line px-3.5 py-2 text-[11px] leading-4 text-warning">
          无法刷新配置状态： {loadError}
        </div>
      )}

      <div className="max-h-72 overflow-y-auto p-1.5">
        {presets.length === 0 ? (
          <div className="px-2.5 py-3 text-[12px] text-fg-muted">
            尚未创建运行方案，可前往设置保存当前配置。
          </div>
        ) : (
          presets.map((preset) => (
            <PresetPopoverRow
              key={`${preset.id}:${preset.updated_at}`}
              preset={preset}
              expanded={expandedId === preset.id}
              onToggle={() =>
                setExpandedId((current) =>
                  current === preset.id ? null : preset.id,
                )
              }
              applyDisabledReason={blocker}
              applying={applying}
              onApply={() => requestApply(preset)}
            />
          ))
        )}
      </div>
      {confirmDialog}
    </div>
  );
}

function PresetPopoverRow({
  preset,
  expanded,
  onToggle,
  applyDisabledReason,
  applying,
  onApply,
}: {
  preset: PresetSummary;
  expanded: boolean;
  onToggle: () => void;
  applyDisabledReason: string | null;
  applying: boolean;
  onApply: () => void;
}) {
  const issueCount = parseValidationIssues(preset.validation_issues).length;
  const applicable = applyDisabledReason === null && issueCount === 0;

  return (
    <div className="rounded-lg px-2 py-1.5 transition-colors hover:bg-hover">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={onToggle}
          title={expanded ? "收起详情" : "方案内容"}
        >
          {expanded ? (
            <ChevronDown size={12} className="shrink-0 text-fg-faint" />
          ) : (
            <ChevronUp size={12} className="shrink-0 text-fg-faint" />
          )}
          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">
            {preset.name}
          </span>
        </button>
        {preset.matches_current && <Badge tone="green">匹配当前配置</Badge>}
        {issueCount > 0 && (
          <Badge tone="yellow" title="此方案引用的配置存在问题">
            <AlertTriangle size={10} /> {issueCount}
          </Badge>
        )}
        {(
          <Button
            variant="outline"
            size="xs"
            disabled={!applicable}
            loading={applying}
            title={
              applyDisabledReason ?? "查看变化并应用方案"
            }
            onClick={onApply}
          >
            应用
          </Button>
        )}
      </div>
      {preset.description !== "" && (
        <div className="mt-0.5 truncate pl-5 text-[11px] text-fg-muted">
          {preset.description}
        </div>
      )}
      {expanded && <PresetRowDetail preset={preset} />}
    </div>
  );
}

/** Stored declarations, loaded when a row is expanded. */
function PresetRowDetail({ preset }: { preset: PresetSummary }) {
  const clients = useConnectionStore((s) => s.clients);
  const current = useConfigDraftStore((state) => state.saved);
  const [detail, setDetail] = useState<Preset | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (clients === null) return;
    let cancelled = false;
    clients.config.getPreset(preset.id).then(
      (value) => {
        if (!cancelled) setDetail(value);
      },
      (cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [clients, preset.id, preset.updated_at, current]);

  if (error !== null) {
    return (
      <div className="mt-1.5 pl-5 text-[11px] text-danger">
        无法读取方案内容： {error}
      </div>
    );
  }
  if (detail === null) {
    return (
      <div className="mt-1.5 flex items-center gap-1.5 pl-5 text-[11px] text-fg-faint">
        <Loader2 size={11} className="animate-spin-slow" /> 正在读取方案内容…
      </div>
    );
  }
  const definition = decodePresetDefinition(detail.definition);
  return <div className="mt-2 max-h-80 overflow-y-auto pl-5">
    {definition ? <PresetContent definition={definition} /> : <p>无法读取方案内容。</p>}
  </div>;
}
