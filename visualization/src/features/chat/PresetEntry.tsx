/**
 * The Composer run-plan quick entry (implementation plan §5.2).
 *
 * Collapsed it shows only the plan matching the running configuration, or
 * "Custom" when there is none or the running configuration has diverged.
 * The popover lists every plan with its match state and, on demand, the
 * managed groups and key budget summary from the stored snapshot; "Manage
 * plans" routes to the settings plans page.
 *
 * Activation is allowed only while the backend declares the configuration
 * reloadable (`activity.can_reload`) — a busy Agent keeps the list readable
 * but the apply action disabled with the real reason, and no optimistic
 * "switched" state is ever shown: the active badge only comes from the
 * re-read snapshots after a successful apply. Switching a plan and starting
 * a turn stay two explicit operations. The apply shares the §15 draft guard
 * through usePresetApplyFlow.
 */

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Layers,
  Loader2,
  Settings2,
  X,
} from "lucide-react";

import type { Preset, PresetSummary } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { ensureConfigLoaded } from "../settings/applyController";
import {
  activationBlocker,
  useConfigDraftStore,
} from "../settings/draft/store";
import { useSettingsUiStore } from "../settings/uiStore";
import { usePresetApplyFlow } from "../settings/presets/PresetDraftConfirm";
import {
  budgetSummary,
  decodePresetSnapshot,
  parseValidationIssues,
  presetScopes,
} from "../settings/presets/presetsModel";
import { valuePreview } from "../settings/editors/controls";

export function PresetEntry() {
  const phase = useConnectionStore((s) => s.phase);
  const clients = useConnectionStore((s) => s.clients);
  const connected = phase === "connected" && clients !== null;
  const loadPhase = useConfigDraftStore((s) => s.loadPhase);
  const loadError = useConfigDraftStore((s) => s.loadError);
  const presets = useConfigDraftStore((s) => s.presets);
  const [open, setOpen] = useState(false);

  // Lazy config snapshots shared with the settings pages; one load per
  // connection (see ensureConfigLoaded).
  useEffect(() => {
    if (clients !== null) ensureConfigLoaded(clients);
  }, [clients]);

  if (!connected) return null;

  const activePreset = presets?.find((preset) => preset.active_match) ?? null;
  const label =
    loadPhase !== "ready" && presets === null
      ? "Run plans"
      : (activePreset?.name ?? "Custom");

  return (
    <div data-slot="preset-entry" className="relative">
      <button
        type="button"
        title={
          activePreset !== null
            ? `Running plan: ${activePreset.name}`
            : "No plan matches the running configuration (custom)"
        }
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-bg-elev px-2.5 text-[11.5px] font-medium text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
      >
        {loadPhase === "loading" && presets === null ? (
          <Loader2 size={12} className="animate-spin-slow" />
        ) : (
          <Layers size={12} />
        )}
        <span className="max-w-28 truncate">{label}</span>
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
  const applyFailure = useConfigDraftStore((s) => s.applyFailure);
  const clearApplyFailure = useConfigDraftStore((s) => s.clearApplyFailure);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const { requestApply, confirmDialog, applying } = usePresetApplyFlow({
    onReview: () => goToSettings("overview"),
  });

  function goToSettings(page: "plans" | "overview" = "plans") {
    useAppStore.getState().setActiveTab("settings");
    useSettingsUiStore.getState().navigateTo(page);
    onClose();
  }

  // Dismiss on Escape and on outside pointer-down.
  useEffect(() => {
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
  }, [onClose]);

  return (
    <div
      ref={rootRef}
      className="absolute right-0 bottom-full z-(--z-drawer) mb-2 w-84 rounded-xl border border-line bg-bg-elev shadow-pop"
    >
      <div className="flex items-center gap-2 border-b border-line px-3.5 py-2.5">
        <span className="min-w-0 flex-1 text-[12.5px] font-semibold">
          Run plans
        </span>
        <Button variant="ghost" size="xs" onClick={() => goToSettings("plans")}>
          <Settings2 size={12} /> Manage plans
        </Button>
      </div>

      {applyFailure !== null && (
        <div className="flex items-start gap-2 border-b border-line bg-danger-soft px-3.5 py-2 text-[11.5px] leading-4 text-danger">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1 break-words">
            The plan was not applied; your changes are kept.{" "}
            {applyFailure.message}
          </span>
          <button
            className="shrink-0 opacity-70 hover:opacity-100"
            onClick={() => clearApplyFailure()}
          >
            <X size={12} />
          </button>
        </div>
      )}

      {blocker !== null && (
        <div className="border-b border-line px-3.5 py-2 text-[11px] leading-4 text-fg-faint">
          Switching is unavailable right now: {blocker}
        </div>
      )}
      {loadError !== null && (
        <div className="border-b border-line px-3.5 py-2 text-[11px] leading-4 text-warning">
          The configuration state could not be refreshed: {loadError}
        </div>
      )}

      <div className="max-h-72 overflow-y-auto p-1.5">
        {presets.length === 0 ? (
          <div className="px-2.5 py-3 text-[12px] text-fg-muted">
            No run plans yet. Capture one from the settings plans page.
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
  const applicable = applyDisabledReason === null && !preset.active_match;

  return (
    <div className="rounded-lg px-2 py-1.5 transition-colors hover:bg-hover">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={onToggle}
          title={expanded ? "Hide details" : "Managed groups and budgets"}
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
        {preset.active_match ? (
          <Badge tone="green">active</Badge>
        ) : preset.saved_match ? (
          <Badge tone="blue">matches saved</Badge>
        ) : null}
        {issueCount > 0 && (
          <Badge tone="yellow" title="Dependencies of this plan are currently missing">
            <AlertTriangle size={10} /> {issueCount}
          </Badge>
        )}
        {!preset.active_match && (
          <Button
            variant="outline"
            size="xs"
            disabled={!applicable}
            loading={applying}
            title={
              applyDisabledReason ?? "Apply this plan (the draft guard may ask first)"
            }
            onClick={onApply}
          >
            Apply
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

/** Managed groups + key budget summary from the stored snapshot (lazy read). */
function PresetRowDetail({ preset }: { preset: PresetSummary }) {
  const clients = useConnectionStore((s) => s.clients);
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
  }, [clients, preset.id, preset.updated_at]);

  if (error !== null) {
    return (
      <div className="mt-1.5 pl-5 text-[11px] text-danger">
        The stored snapshot could not be read: {error}
      </div>
    );
  }
  if (detail === null) {
    return (
      <div className="mt-1.5 flex items-center gap-1.5 pl-5 text-[11px] text-fg-faint">
        <Loader2 size={11} className="animate-spin-slow" /> Loading the stored snapshot…
      </div>
    );
  }
  const snapshot = decodePresetSnapshot(detail.snapshot);
  const budgets = snapshot === null ? [] : budgetSummary(snapshot);
  return (
    <div className="mt-1.5 space-y-1.5 pl-5 text-[11px] leading-4 text-fg-muted">
      <div>
        Manages:{" "}
        {presetScopes(preset).map((scope) => scope.title).join(" · ")}
        {!preset.included_scopes.includes("budgets") &&
          " — budgets stay as they are."}
      </div>
      {budgets.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10.5px] text-fg-faint">
          {budgets.map((row) => (
            <span key={row.path}>
              {row.path}={valuePreview(row.value, 16)}
            </span>
          ))}
        </div>
      )}
      {preset.active_match && (
        <div className="flex items-center gap-1 text-success">
          <CheckCircle2 size={11} /> Matches the running configuration.
        </div>
      )}
    </div>
  );
}
