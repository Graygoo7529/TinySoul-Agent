/**
 * Part of the LLM Models settings page (split from LlmModelsPage).
 */

import { useI18n } from "../../../../i18n";
import {
  useState,
} from "react";
import {
  ArrowRightLeft,
} from "lucide-react";
import {
  Button,
} from "../../../../components/ui/Button";
import { Modal } from "../../../../components/ui/Modal";
import { useConfigDraftStore } from "../../draft/store";
import {
  providersForAdapter,
} from "../../draft/catalog";
import {
  stringField,
  type ProjectedObject,
} from "../collectionDrafts";
import {
  selectClass,
} from "../modelControls";

// ---------------------------------------------------------------------------
// Adapter change confirmation
// ---------------------------------------------------------------------------

export function AdapterChangeModal({
  object,
  change,
  providers,
  onClose,
  onConfirm,
}: {
  object: ProjectedObject;
  change: { adapter: string; providerId: string };
  providers: ProjectedObject[];
  onClose: () => void;
  onConfirm: (providerId: string, retainOptions: boolean) => void;
}) {
  const { t } = useI18n();
  const [providerId, setProviderId] = useState(change.providerId);
  const [retainOptions, setRetainOptions] = useState(true);
  const matching = providersForAdapter(useConfigDraftStore.getState().catalog, providers, change.adapter);
  return (
    <Modal title={t("settings.changeAdapter")} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-md border border-line bg-bg-sunken/40 px-3 py-3">
          <div>
              <div className="text-[10px] text-fg-faint">{t("settings.currentValue")}</div>
            <div className="mt-0.5 font-mono text-[12px] text-fg">
              {stringField(object.value, "adapter")}
            </div>
          </div>
          <ArrowRightLeft size={14} className="text-fg-faint" />
          <div>
              <div className="text-[10px] text-fg-faint">{t("settings.targetValue")}</div>
            <div className="mt-0.5 font-mono text-[12px] text-fg">{change.adapter}</div>
          </div>
        </div>
        <label className="flex items-center gap-2 text-[12px]">
          <input type="checkbox" checked={retainOptions} onChange={(event) => setRetainOptions(event.target.checked)} />
          {t("settings.keepSupportedOptions")}</label>
        <p className="text-[11px] leading-4 text-fg-muted">
          {t("settings.changeAdapterHint")}</p>
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">{t("settings.provider")}</span>
          <select
            aria-label={t("settings.targetProvider")}
            value={providerId}
            onChange={(event) => setProviderId(event.target.value)}
            className={selectClass}
          >
            {matching.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.id}
              </option>
            ))}
          </select>
        </label>
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>{t("settings.cancel")}</Button>
          <Button
            size="xs"
            variant="primary"
            disabled={providerId === ""}
            onClick={() => onConfirm(providerId, retainOptions)}
          >
            <ArrowRightLeft size={13} />
            {t("settings.switchAdapter")}</Button>
        </div>
      </div>
    </Modal>
  );
}
