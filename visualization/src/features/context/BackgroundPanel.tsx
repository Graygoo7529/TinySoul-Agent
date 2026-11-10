import { useI18n } from "../../i18n";
import { requestIdForTurn } from "../../store/turnStore";
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { BackgroundPage, BackgroundResource } from "../../api/v2/types";
import { drainPages } from "../../api/v2/clients/paging";
import { useConnectionStore } from "../../store/connectionStore";
import { Markdown } from "../../components/markdown/Markdown";
import { EmptyState } from "../../components/ui/EmptyState";
import { contextClients, errorMessage } from "./panelShared";
import { asObject, asString } from "../trace/model/facts";
import type { MarkdownOrigin } from "../../components/markdown/codeBlockRegistry";

/** Read installed content or its immutable completion snapshot, never Home.read_top. */
export function BackgroundPanel({ epoch, turnId, day, active, committed, reflection = false, owner }: {
  epoch: number; turnId: string; day: string; active: boolean; committed: boolean; reflection?: boolean; owner: "home" | "memory";
}) {
  const { t } = useI18n();
  const generation = useConnectionStore((s) => s.contextGeneration);
  const [data, setData] = useState<{ items: BackgroundResource[]; available: boolean; source: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(new Set<string>());
  useEffect(() => {
    if (reflection && !active) return;
    const controller = new AbortController();
    const clients = contextClients(epoch);
    void drainPages<BackgroundResource, BackgroundPage>((continuation) => {
      const params = { max_chars: 65536, ...(continuation ? { continuation } : {}) };
      return active ? clients.context.background(requestIdForTurn(turnId), params, { signal: controller.signal })
        : clients.session.background(turnId, { ...params, day }, { signal: controller.signal });
    }, { signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) { setData({ items: result.items, available: result.pages[0].snapshot_available, source: result.pages[0].source }); setError(null); }
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(errorMessage(reason)); });
    return () => controller.abort();
  }, [epoch, turnId, day, active, committed, reflection, active ? generation : 0]);
  const resources = data?.items.filter((item) => item.owner === owner) ?? [];
  return <div className="space-y-3" data-background-source={data?.source}>
    <div className="text-[11px] text-fg-faint">{reflection && !active ? t("context.reflectionRetained") : data?.source === "session" ? t("context.sessionBackground") : t("context.loadedThisTurn")}</div>
    {error && <div className="text-[12px] text-warning">{error}</div>}
    {!data && !error && (reflection && !active ? <EmptyState title={t("context.noReflectionBackground")} description={t("context.inspectModelHint")} /> : <Loader2 size={14} className="animate-spin-slow text-fg-faint" />)}
    {data && !data.available && <EmptyState title={t("context.noSavedBackground")} />}
    {data?.available && resources.length === 0 && <EmptyState title={t("context.ownerNotLoaded", { owner: owner === "home" ? t("shell.home") : t("shell.memory") })} />}
    {resources.map((item) => <ResourceCard key={item.ref} item={item} expanded={expanded.has(item.ref)}
      origin={{ ref: item.ref, turnId, day, view: "history" }} onToggle={() => setExpanded((current) => {
        const next = new Set(current); if (next.has(item.ref)) next.delete(item.ref); else next.add(item.ref); return next;
      })} />)}
  </div>;
}

function ResourceCard({ item, expanded, onToggle, origin }: {
  item: BackgroundResource; expanded: boolean; onToggle: () => void; origin: MarkdownOrigin;
}) {
  const { t } = useI18n();
  const body = resourceBody(item);
  const title = item.title && item.title !== item.ref ? item.title : body.text.match(/^#\s+(.+)$/m)?.[1] ?? item.ref;
  const summary = body.text.split("\n").map((line) => line.trim()).find((line) => line.length > 0 && !line.startsWith("#")) ?? "";
  const source = { default: t("context.defaultLoad"), automatic: t("context.automaticLoad"), phase1: t("context.onDemandLoad") }[item.source];
  return <article className="overflow-hidden rounded-xl border border-line bg-bg-elev shadow-card">
    <button type="button" className="block w-full text-left px-3 py-2.5 hover:bg-hover" onClick={onToggle} aria-expanded={expanded}>
      <div className="flex items-center gap-2">
        {expanded ? <ChevronDown size={13} className="shrink-0 text-accent" /> : <ChevronRight size={13} className="shrink-0 text-fg-faint" />}
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium">{title}</span>
        <span className="shrink-0 text-[10px] text-fg-faint">{source} · {body.text.length} {t("common.characters")}</span>
      </div>
      <div className="mt-1 truncate pl-5 font-mono text-[10px] text-fg-faint" title={item.ref}>{item.ref}</div>
      {!expanded && summary && <div className="mt-1 line-clamp-1 pl-5 text-[11px] text-fg-muted">{summary}</div>}
    </button>
    {expanded && <div className="border-t border-line/60 px-3 py-2">
      {body.day && <div className="mb-1 text-[10px] text-fg-faint">{body.day}</div>}
      <Markdown density="compact" origin={{ ...origin, ref: body.ref ?? origin.ref }}>{body.text}</Markdown>
    </div>}
  </article>;
}

/** Memory's dynamic projection has one owner metadata header followed by Markdown. */
function resourceBody(item: BackgroundResource): { text: string; day?: string; ref?: string } {
  if (["memory:current", "memory:latest", "memory:target"].includes(item.ref)) {
    const split = item.content.indexOf("\n\n");
    if (split > 0) {
      try {
        const metadata = asObject(JSON.parse(item.content.slice(0, split)) as unknown);
        if (metadata?.ref === item.ref) return { text: item.content.slice(split + 2),
          day: asString(metadata.day) ?? undefined, ref: asString(metadata.resolved_ref) ?? undefined };
      } catch { /* Unrecognized content remains visible in full. */ }
    }
  }
  return { text: item.content };
}
