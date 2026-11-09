import { hueForId } from "../../../utils/hue";
import { useI18n } from "../../../i18n";
import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";
import { Badge } from "../../../components/ui/Badge";
import { Modal } from "../../../components/ui/Modal";
import { stringField, type ProjectedObject } from "./collectionDrafts";
import { inputClass } from "./modelControls";
import { useConfigDraftStore } from "../draft/store";
import { adapterRule } from "../draft/catalog";

/** The same candidate list is used for model navigation and task selection. */
export function ModelSelectionList({ models, value, onSelect, disabledIds = [] }: {
  models: ProjectedObject[];
  value: string | null;
  onSelect: (id: string) => void;
  disabledIds?: readonly string[];
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  // null = all; empty string = models without a family.
  const [family, setFamily] = useState<string | null>(null);
  const [showCollapsed, setShowCollapsed] = useState(false);
  const [showUnavailable, setShowUnavailable] = useState(false);
  const catalog = useConfigDraftStore((state) => state.catalog);
  const available = (model: ProjectedObject) => adapterRule(catalog, stringField(model.value, "adapter"))?.runtimeAvailable !== false;
  const families = [...new Set(models.map((model) => stringField(model.value, "family")))].sort(familyOrder);
  const needle = query.trim().toLocaleLowerCase();
  const visible = models.filter((model) => {
    const group = stringField(model.value, "family");
    return (showUnavailable || available(model)) && (family === null || family === group)
      && (needle !== "" ? `${model.id} ${group}`.toLocaleLowerCase().includes(needle)
        : showCollapsed || model.value.collapsed !== true);
  }).sort((a, b) => familyOrder(stringField(a.value, "family"), stringField(b.value, "family")) || a.id.localeCompare(b.id));

  return <div className="min-w-0" data-slot="model-selection-list">
    <div className="space-y-2 border-b border-line p-3">
      <input aria-label={t("settings.searchModels")} placeholder={t("settings.searchModelsPlaceholder")} className={inputClass}
        value={query} onChange={(event) => setQuery(event.target.value)} />
      <div className="flex flex-wrap gap-1" aria-label={t("settings.modelFamily")}>
        {[null, ...families].map((item) => {
          const tinted = item !== null && item !== "";
          return <button type="button" key={item === null ? "all" : `family:${item}`}
            aria-pressed={family === item} onClick={() => setFamily(item)}
            style={tinted ? { "--fh": String(hueForId(item)) } as CSSProperties : undefined}
            className={tinted
              ? `fam-chip rounded-full border px-2 py-0.5 text-[11px] ${family === item ? "fam-chip-on" : ""}`
              : `rounded-full border px-2 py-0.5 text-[11px] ${family === item ? "border-accent bg-accent-soft text-accent" : "border-line text-fg-muted hover:bg-hover"}`}>
            {item === null ? t("settings.all") : item || t("settings.ungrouped")}
          </button>;
        })}
      </div>
      <label className="flex items-center gap-1.5 text-[11px] text-fg-muted">
        <input type="checkbox" checked={showCollapsed} onChange={(event) => setShowCollapsed(event.target.checked)} />{t("settings.showCollapsedModels")}</label>
      <label className="flex items-center gap-1.5 text-[11px] text-fg-muted">
        <input type="checkbox" checked={showUnavailable} onChange={(event) => setShowUnavailable(event.target.checked)} />{t("settings.showUnconnectedModels")}</label>
    </div>
    <div className="max-h-80 space-y-1 overflow-y-auto p-2">
      {visible.map((model, index) => {
        const group = stringField(model.value, "family");
        const disabled = disabledIds.includes(model.id);
        return <div key={model.id}>
          {(index === 0 || group !== stringField(visible[index - 1].value, "family")) &&
            <div className={`px-2 py-1 text-[11px] font-semibold ${group !== "" ? "fam-head" : ""} text-fg-faint`}
              style={group !== "" ? { "--fh": String(hueForId(group)) } as CSSProperties : undefined}>
              {group || t("settings.ungrouped")}</div>}
          <button type="button" disabled={disabled} aria-pressed={value === model.id}
            onClick={() => onSelect(model.id)}
            className={`flex w-full flex-wrap items-center gap-1.5 rounded-md px-2 py-2 text-left text-[12px] disabled:opacity-45 ${value === model.id ? "bg-active text-accent" : "hover:bg-hover"}`}>
            {value === model.id && <Check size={12} />}
            <span className="min-w-0 flex-1 break-all font-mono">{model.id}</span>
            {model.value.collapsed === true && <Badge tone="gray">{t("settings.collapsedByDefault")}</Badge>}
            {!available(model) && <Badge tone="yellow">{t("settings.notCallable")}</Badge>}
            {model.isNew ? <Badge tone="accent">{t("settings.newBadge")}</Badge> : model.dirty && <Badge tone="accent">{t("common.modified")}</Badge>}
            {disabled && <span className="text-[10px]">{t("settings.inTaskChain")}</span>}
          </button>
        </div>;
      })}
      {visible.length === 0 && <p className="p-3 text-[12px] text-fg-muted">{t("settings.noMatchingModels")}</p>}
    </div>
  </div>;
}

function familyOrder(a: string, b: string): number {
  return a === b ? 0 : a === "" ? 1 : b === "" ? -1 : a.localeCompare(b);
}

/** Filters never change the bound ID; only a confirmed row selection does. */
export function ModelPicker({ models, value, onSelect, disabledIds, disabled = false, label, adding = false }: {
  models: ProjectedObject[];
  value: string | null;
  onSelect: (id: string) => void;
  disabledIds?: readonly string[];
  disabled?: boolean;
  label: string;
  adding?: boolean;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (open) panel.current?.querySelector("input")?.focus();
  }, [open]);
  return <>
    <button ref={trigger} type="button" disabled={disabled} aria-label={label} aria-haspopup="dialog" aria-expanded={open}
      onClick={() => setOpen(true)} className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12px] disabled:opacity-50">
      {adding && <Plus size={12} />}
      <span className="min-w-0 flex-1 truncate text-left font-mono">{adding ? t("settings.addModel") : value || t("settings.selectModel")}</span>
      {!adding && value && !models.some((model) => model.id === value) && <Badge tone="yellow">{t("settings.overview.sourceMissing")}</Badge>}
      {!adding && <ChevronDown size={12} />}
    </button>
    {open && <Modal title={adding ? t("settings.addModel") : t("settings.selectModel")} onClose={close}>
      <div ref={panel} role="dialog" aria-label={label}>
        <ModelSelectionList models={models} value={value} disabledIds={disabledIds} onSelect={(id) => { onSelect(id); close(); }} />
      </div>
    </Modal>}
  </>;
}
