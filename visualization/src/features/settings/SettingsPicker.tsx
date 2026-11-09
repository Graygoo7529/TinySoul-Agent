import { useI18n } from "../../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Menu, X } from "lucide-react";

import { pageIcon } from "./navIcons";
import { useSettingsUiStore } from "./uiStore";

/** Compact pages trigger: the current page's line icon (location at a
 *  glance) with a faint menu hint below. */
function PagesTriggerIcon() {
  const page = useSettingsUiStore((s) => s.page);
  const Icon = pageIcon(page);
  return (
    <span className="flex h-full w-full flex-col items-center justify-between py-2.5">
      <Icon size={16} strokeWidth={1.75} className="text-accent" />
      <Menu size={12} className="opacity-40" />
    </span>
  );
}

/** Object-list trigger icon: the current page's line icon — the list belongs
 *  to the page you are on. */
function TriggerIcon() {
  const page = useSettingsUiStore((s) => s.page);
  const Icon = pageIcon(page);
  return <Icon size={15} strokeWidth={1.75} className="shrink-0 text-fg-faint" />;
}

/** One navigation list, persistent on wide layouts and a panel on compact layouts.
 * The editor remains a sibling, so opening/resizing never remounts its inputs. */
export function SettingsPicker({ kind, label, suggestOpen = false, children }: {
  kind: "pages" | "objects";
  label: ReactNode;
  /** Objects pickers: open the panel once on entry when nothing is selected
      yet (compact layouts only — the trigger is only visible there). */
  suggestOpen?: boolean;
  children: (close: () => void) => ReactNode;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const suggested = useRef(false);
  useEffect(() => {
    if (!suggestOpen || suggested.current) return;
    if (trigger.current && trigger.current.getClientRects().length > 0) {
      suggested.current = true;
      setOpen(true);
    }
  }, [suggestOpen]);
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  useEffect(() => {
    if (!open) return;
    const content = panel.current;
    (content?.querySelector<HTMLElement>('input:not([type="checkbox"])') ?? content?.querySelector<HTMLElement>('button'))?.focus();
    // A compact panel becomes the persistent list again on a wide layout.
    const resize = new ResizeObserver(() => {
      if (trigger.current && trigger.current.getClientRects().length === 0) setOpen(false);
    });
    if (trigger.current) resize.observe(trigger.current);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close(); }
      if (event.key !== "Tab" || !content) return;
      const focusable = [...content.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')]
        .filter((element) => element.getClientRects().length > 0);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { resize.disconnect(); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return <div className="settings-picker" data-kind={kind} data-open={open}>
    <button ref={trigger} type="button" className="settings-picker-trigger focus-ring" aria-expanded={open} aria-haspopup="dialog"
      aria-label={kind === "pages" ? t("settings.nav.label") : undefined} title={kind === "pages" ? t("settings.nav.label") : undefined}
      onClick={() => setOpen(true)}>
      {kind === "pages" ? <PagesTriggerIcon /> : <><TriggerIcon /><span className="min-w-0 flex-1 truncate text-left">{label}</span><ChevronDown size={14} /></>}
    </button>
    {open && <button type="button" tabIndex={-1} aria-label={t("settings.closePicker")} className="settings-picker-backdrop" onClick={close} />}
    <div ref={panel} className="settings-picker-panel" role={open ? "dialog" : undefined} aria-modal={open || undefined}
      aria-label={kind === "pages" ? t("settings.nav.label") : t("settings.selectObject")}>
      <div className="settings-picker-heading">
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <button type="button" onClick={close} aria-label={t("settings.overview.close")} className="focus-ring rounded-md p-1.5 hover:bg-hover"><X size={16} /></button>
      </div>
      {children(close)}
    </div>
  </div>;
}
