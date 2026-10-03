import { useEffect, useRef, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Badge } from "../../components/ui/Badge";
import { draftIssues, useConfigDraftStore } from "./draft/store";
import { useSettingsUiStore } from "./uiStore";

/** Native disclosure keeps editors mounted, and reveals errors/search targets. */
export function SettingsDisclosure({ title, paths = [], children, meta, className = "" }: {
  title: ReactNode; paths?: string[]; children: ReactNode; meta?: ReactNode; className?: string;
}) {
  const details = useRef<HTMLDetailsElement>(null);
  const state = useConfigDraftStore();
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  const owns = (path: string) => paths.some((prefix) => path === prefix || path.startsWith(`${prefix}.`));
  const dirty = Object.values(state.drafts).some((entry) => owns(entry.path));
  const issues = draftIssues(state).filter((issue) => owns(issue.path));
  const failureKey = state.applyFailure?.kind === "config-invalid" ? state.applyFailure.key : null;
  const errorCount = issues.length + (failureKey !== null && owns(failureKey) ? 1 : 0);
  const targeted = focusPath !== null && owns(focusPath);
  useEffect(() => {
    if ((targeted || errorCount > 0) && details.current) details.current.open = true;
  }, [targeted, errorCount]);
  return <details ref={details} className={`settings-disclosure group rounded-lg border border-line bg-bg-elev ${className}`}
    data-settings-paths={paths.join(" ")}>
    <summary className="focus-ring flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2.5 text-[13px] font-medium hover:bg-hover [&::-webkit-details-marker]:hidden">
      <ChevronRight size={13} className="shrink-0 text-fg-faint transition-transform group-open:rotate-90" />
      <span className="min-w-0 flex-1">{title}</span>
      {errorCount > 0 ? <Badge tone="yellow">{errorCount} 项问题</Badge> : dirty ? <Badge tone="accent">已修改</Badge> : null}
      {meta}
    </summary>
    <div className="min-w-0 border-t border-line">{children}</div>
  </details>;
}
