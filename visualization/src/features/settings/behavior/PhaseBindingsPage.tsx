import { useI18n } from "../../../i18n";
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
  const { t } = useI18n();
  return (
    <SettingsPageBody>
      <FieldSection
        title={t("settings.cyclePhases")}
        description={t("settings.theTaskChainsCalledByTheTwoModelTasks")}
        paths={[PHASE1_PATH, PHASE2_PATH]}
        overrides={{
          [PHASE1_PATH]: {
            render: (api) => (
              <TaskChainRefControl api={api} ownerDefault="frame-stage1" />
            ),
          },
          [PHASE2_PATH]: {
            render: (api) => (
              <TaskChainRefControl api={api} ownerDefault="frame-stage2" />
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
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const chains = projectCollection(state, "llm.tasks");
  const current = typeof api.value === "string" ? api.value : "";
  const known = current !== "" && chains.some((chain) => chain.id === current);

  return (
    <span className="flex items-center gap-1.5">
      <select
        aria-label={t("settings.consumerTaskChain", { consumer: api.path })}
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
        <option value="">{ownerDefault}{t("settings.default")}</option>
        {current !== "" && !known && (
          <option value={current}>{current}{t("settings.unknown")}</option>
        )}
        {chains.map((chain) => (
          <option key={chain.id} value={chain.id}>
            {chain.id}
            {chain.isNew ? t("settings.newDraftSuffix") : ""}
          </option>
        ))}
      </select>
      {known && (
        <button
          type="button"
          className="flex items-center gap-1 text-[12px] font-medium whitespace-nowrap text-accent hover:underline"
          onClick={() => navigateTo("llm-tasks", `llm.tasks.${current}`)}
        >{t("settings.openChain")}<ArrowRight size={12} />
        </button>
      )}
    </span>
  );
}
