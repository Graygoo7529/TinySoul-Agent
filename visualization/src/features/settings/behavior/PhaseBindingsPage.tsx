/**
 * Phase Bindings settings page (config-coverage §3.1): which task chain the
 * framework Phase1/Phase2 tasks call. The pickers read the projected
 * `llm.tasks` collection draft-aware — a chain created in the same draft is
 * already selectable — and link back to the Task Chains page. Edits stage
 * drafts only; apply stays authoritative.
 */

import { ArrowRight } from "lucide-react";

import { useConfigDraftStore } from "../draft/store";
import { projectCollection } from "../models/collectionDrafts";
import { useSettingsUiStore } from "../uiStore";
import {
  FieldSection,
  SettingsPageBody,
  type DraftFieldApi,
} from "../editors/controls";

const PHASE1_PATH = "loop.cycle.phase1_task_profile";
const PHASE2_PATH = "loop.cycle.phase2_task_profile";

export function PhaseBindingsPage() {
  return (
    <SettingsPageBody>
      <FieldSection
        title="Cycle Phases"
        description="The task chains called by the two model tasks of every Agent Cycle. Phase 1 updates the Context and selects action domains; Phase 2 generates the Action calls inside them."
        paths={[PHASE1_PATH, PHASE2_PATH]}
        overrides={{
          [PHASE1_PATH]: {
            render: (api) => (
              <TaskChainRefControl api={api} ownerDefault="frame_stage1" />
            ),
          },
          [PHASE2_PATH]: {
            render: (api) => (
              <TaskChainRefControl api={api} ownerDefault="frame_stage2" />
            ),
          },
        }}
      />
    </SettingsPageBody>
  );
}

/**
 * Reference control for one phase binding: options are the projected task
 * chains (draft-aware). The empty choice withdraws the override, restoring
 * the code-owned default chain.
 */
function TaskChainRefControl({
  api,
  ownerDefault,
}: {
  api: DraftFieldApi;
  ownerDefault: string;
}) {
  const state = useConfigDraftStore();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const chains = projectCollection(state, "llm.tasks");
  const current = typeof api.value === "string" ? api.value : "";
  const known = current !== "" && chains.some((chain) => chain.id === current);

  return (
    <span className="flex items-center gap-1.5">
      <select
        aria-label={`${api.path} task chain`}
        className="h-8 w-56 rounded-md border border-line bg-bg px-2 font-mono text-[12.5px] text-fg outline-none transition-colors focus:border-accent disabled:opacity-50"
        value={current}
        disabled={api.readOnly !== null}
        onChange={(event) => {
          const next = event.target.value;
          if (next === "") {
            api.clear();
          } else {
            api.set(next);
          }
        }}
      >
        <option value="">{ownerDefault} (default)</option>
        {current !== "" && !known && (
          <option value={current}>{current} (unknown)</option>
        )}
        {chains.map((chain) => (
          <option key={chain.id} value={chain.id}>
            {chain.id}
            {chain.isNew ? " (new in draft)" : ""}
          </option>
        ))}
      </select>
      {known && (
        <button
          type="button"
          className="flex items-center gap-1 text-[12px] font-medium whitespace-nowrap text-accent hover:underline"
          onClick={() => navigateTo("llm-tasks", `llm.tasks.${current}`)}
        >
          Open chain <ArrowRight size={12} />
        </button>
      )}
    </span>
  );
}
