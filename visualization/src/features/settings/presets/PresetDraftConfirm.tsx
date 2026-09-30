/**
 * The §15/§5.2 draft-conflict flow shared by every run-plan apply entry
 * (the settings plans page and the Composer quick entry).
 *
 * With an unapplied ConfigDraft, a plan switch must be an explicit choice:
 * - review the changes first (return to settings to apply or discard them),
 * - discard the unapplied changes and switch — submits only `{preset_id}`
 *   and clears the agreed drafts only after the activation succeeds, or
 * - cancel the switch, which keeps the draft.
 *
 * The flow never merges the draft into the plan and never sends a draft
 * apply followed by a plan apply.
 */

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import type { PresetSummary } from "../../../api/v2/types";
import { Button } from "../../../components/ui/Button";
import { Modal } from "../../../components/ui/Modal";
import { useConnectionStore } from "../../../store/connectionStore";
import { selectDraftCount, useConfigDraftStore } from "../draft/store";
import { applyPreset } from "./presetsController";

export function PresetDraftConfirm({
  preset,
  draftCount,
  applying,
  onReview,
  onDiscardAndApply,
  onCancel,
}: {
  preset: PresetSummary;
  draftCount: number;
  applying: boolean;
  /** "Return to settings" — the user applies or discards the draft there. */
  onReview: () => void;
  /** Confirmed: give up the unapplied changes and switch to the plan. */
  onDiscardAndApply: () => void;
  /** Cancel the switch; the draft is kept. */
  onCancel: () => void;
}) {
  return (
    <Modal title="Unsaved configuration changes" onClose={onCancel}>
      <div className="flex items-start gap-2.5 text-[13px] leading-5 text-fg">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" />
        <div>
          You have {draftCount} unapplied{" "}
          {draftCount === 1 ? "change" : "changes"} in settings. Switching to{" "}
          <span className="font-medium">“{preset.name}”</span> applies the plan
          as-is — the two are never merged, and the plan is applied with a
          single request.
        </div>
      </div>
      <div className="mt-4 flex flex-col gap-2">
        <Button variant="outline" size="sm" onClick={onReview}>
          Review my changes first
        </Button>
        <Button
          variant="danger"
          size="sm"
          loading={applying}
          onClick={onDiscardAndApply}
        >
          Discard changes and switch to “{preset.name}”
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel — keep my changes
        </Button>
      </div>
    </Modal>
  );
}

/**
 * The apply guard used by both entry points: with a clean draft the plan
 * applies directly; with a dirty draft the shared confirmation opens. The
 * returned `confirmDialog` renders nothing while no switch is pending.
 */
export function usePresetApplyFlow({ onReview }: { onReview: () => void }) {
  const clients = useConnectionStore((s) => s.clients);
  const applying = useConfigDraftStore((s) => s.applyPhase !== "idle");
  const [pending, setPending] = useState<PresetSummary | null>(null);

  const requestApply = (preset: PresetSummary) => {
    if (clients === null) return;
    if (selectDraftCount(useConfigDraftStore.getState()) > 0) {
      setPending(preset);
      return;
    }
    void applyPreset(clients, preset, { discardDraftKeys: [] });
  };

  const confirmDialog =
    pending !== null ? (
      <PresetDraftConfirm
        preset={pending}
        draftCount={selectDraftCount(useConfigDraftStore.getState())}
        applying={applying}
        onCancel={() => setPending(null)}
        onReview={() => {
          setPending(null);
          onReview();
        }}
        onDiscardAndApply={() => {
          if (clients === null) return;
          // Snapshot the agreed keys now; edits made while the request is in
          // flight are new work and survive the cleanup.
          const discardDraftKeys = Object.keys(
            useConfigDraftStore.getState().drafts,
          );
          void applyPreset(clients, pending, { discardDraftKeys }).then(() => {
            // Success or failure, the dialog closes: a failure keeps the
            // draft and surfaces through the shared apply-failure state.
            setPending(null);
          });
        }}
      />
    ) : null;

  return { requestApply, confirmDialog, applying };
}
