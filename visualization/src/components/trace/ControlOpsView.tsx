import { Flag, Layers, ListChecks } from "lucide-react";
import type { ControlOp } from "../../derive/model";
import { DomainChip, LinkChip } from "./semantic";
import { JsonTree } from "../ui/JsonTree";

/**
 * Semantic rendering of Phase1 control-tool operations: domain selection,
 * working-context maintenance (todos / milestones) and background loading.
 */
export function ControlOpsView({ ops }: { ops: ControlOp[] }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
        Control operations
      </div>
      <div className="space-y-1">
        {ops.map((op, i) => (
          <ControlOpRow key={i} op={op} />
        ))}
      </div>
    </div>
  );
}

function ControlOpRow({ op }: { op: ControlOp }) {
  switch (op.kind) {
    case "select_domains":
      return (
        <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-accent-soft px-2.5 py-1.5">
          <Layers size={12} className="shrink-0 text-accent" />
          <span className="text-[12px] text-fg">Selected action domains</span>
          {op.domains.map((domain) => (
            <DomainChip key={domain} domain={domain} />
          ))}
        </div>
      );
    case "set_todo":
      return (
        <div className="flex items-center gap-2 rounded-lg bg-bg-sunken px-2.5 py-1.5 text-[12px]">
          <ListChecks size={12} className="shrink-0 text-accent" />
          <span className="text-fg-muted">set todo</span>
          <span className="min-w-0 flex-1 truncate text-fg">{op.content}</span>
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">
            {op.key} · {op.status}
          </span>
        </div>
      );
    case "remove_todo":
      return (
        <div className="flex items-center gap-2 rounded-lg bg-bg-sunken px-2.5 py-1.5 text-[12px]">
          <ListChecks size={12} className="shrink-0 text-fg-faint" />
          <span className="text-fg-muted">removed todo</span>
          <span className="font-mono text-[11px] text-fg-faint">{op.key}</span>
        </div>
      );
    case "set_milestone":
      return (
        <div className="flex items-center gap-2 rounded-lg bg-warning-soft px-2.5 py-1.5 text-[12px]">
          <Flag size={12} className="shrink-0 text-warning" />
          <span className="text-fg-muted">milestone</span>
          <span className="min-w-0 flex-1 truncate text-fg">{op.content}</span>
          <span className="shrink-0 font-mono text-[10px] text-fg-faint">{op.key}</span>
        </div>
      );
    case "remove_milestone":
      return (
        <div className="flex items-center gap-2 rounded-lg bg-bg-sunken px-2.5 py-1.5 text-[12px]">
          <Flag size={12} className="shrink-0 text-fg-faint" />
          <span className="text-fg-muted">removed milestone</span>
          <span className="font-mono text-[11px] text-fg-faint">{op.key}</span>
        </div>
      );
    case "load_background":
    case "evict_background":
      return (
        <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-bg-sunken px-2.5 py-1.5 text-[12px]">
          <span className={op.kind === "load_background" ? "text-info" : "text-warning"}>
            {op.kind === "load_background" ? "load background" : "evict background"}
          </span>
          {op.links.map((link) => (
            <LinkChip key={link} link={link} />
          ))}
        </div>
      );
    default:
      return (
        <div className="rounded-lg bg-bg-sunken px-2.5 py-1.5 text-[12px]">
          <span className="font-mono text-[11px]">{op.name}</span>
          <JsonTree value={op.arguments} defaultExpanded={false} />
        </div>
      );
  }
}
