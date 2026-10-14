import { useCallback, useEffect, useState } from "react";
import { RotateCw } from "lucide-react";
import { settingsText } from "../i18n";
import type { ContextOverview } from "../../../api/v2/context";
import { requestIdForTurn } from "../../../store/turnStore";
import { useConnectionStore } from "../../../store/connectionStore";
import {
  ClosedBanner,
  contextClients,
  RefreshNotice,
} from "../../context/panelShared";
import { useTurnActivity } from "../../context/activity";

import { FieldSection, SettingsPageBody } from "./controls";
import { SettingsDisclosure } from "../SettingsDisclosure";
import { SectionCard } from "../../../components/ui/Card";
import { useSettingsUiStore } from "../uiStore";
import type { SettingsPageId } from "../pages";

const MEBIBYTE = 1024 * 1024;

/**
 * Context configuration is presented in the same order the kernel installs
 * segments: Background, Trace, then Working. The cards describe composition
 * and owners; each value still writes through the shared settings draft.
 */
export function ContextPage() {
  return (
    <SettingsPageBody>
      <ContextUsageCard />
      <div className="context-rail grid grid-cols-3 overflow-hidden rounded-xl border border-line bg-bg-elev">
        {[
          ["Background", "Session · Home · Memory", "background"],
          ["Trace", "TurnTrace and progressive history", "trace"],
          ["Working", "Plan · Workspace · Jobs", "working"],
        ].map(([title, detail, slot], index) => (
          <div key={slot} className={`relative px-3.5 py-3 ${index > 0 ? "border-l border-line" : ""}`}>
            <div className="text-[11px] font-semibold tracking-wide text-accent uppercase">{title}</div>
            <div className="mt-1 text-[11px] leading-4 text-fg-muted">{detail}</div>
            {index < 2 && <span className="absolute top-1/2 -right-1.5 z-10 h-3 w-3 -translate-y-1/2 rotate-45 border-t border-r border-line bg-bg-elev" />}
          </div>
        ))}
      </div>

      <FieldSection
        title={settingsText("Background")}
        description={settingsText("The stable identity, Session history projection, Home catalog and Memory views assembled before the current turn trace.")}
        paths={["session.max_background_chars", "home.max_skill_catalog_chars"]}
        overrides={{
          "session.max_background_chars": { min: 512, slider: { min: 1024, max: 128 * 1024, step: 1024 } },
          "home.max_skill_catalog_chars": { min: 1, slider: { min: 1024, max: 64 * 1024, step: 1024 } },
        }}
      />

      <FieldSection
        title={settingsText("Context input budget")}
        description={settingsText("The combined inline image byte limit for one constructed MessageStack; it applies across Background, Trace and Working.")}
        paths={["context.max_image_bytes"]}
        overrides={{
          "context.max_image_bytes": { min: 1, slider: { min: MEBIBYTE, max: 64 * MEBIBYTE, step: MEBIBYTE } },
        }}
      />

      <FieldSection
        title={settingsText("Trace")}
        description={settingsText("TurnTrace chunking is a compression target; complete entries remain intact. Inspection is a bounded progressive page.")}
        paths={["context.trace_chunk_chars", "context.trace_branch_factor", "context.trace_min_hot_entries", "context.max_trace_inspect_chars"]}
        overrides={{
          "context.trace_chunk_chars": { min: 1, slider: { min: 1024, max: 64 * 1024, step: 1024 } },
          "context.trace_branch_factor": { min: 2, slider: { min: 2, max: 16 } },
          "context.trace_min_hot_entries": { min: 0, slider: { min: 0, max: 32 } },
          "context.max_trace_inspect_chars": { min: 1024, slider: { min: 1024, max: 64 * 1024, step: 1024 } },
        }}
      />

      <FieldSection
        title={settingsText("Composition")}
        description={settingsText("Optional fixed system identity and journal text used when the MessageStack is rebuilt.")}
        paths={["context.system_text", "context.journal"]}
        forceAdvanced={["context.journal"]}
      />

      <SettingsDisclosure title={settingsText("Pressure and related limits")} paths={["context.compression_trigger_ratio", "context.compression_target_ratio"]}>
        <FieldSection
          title={settingsText("Compression")}
          description={settingsText("Recomposition starts at the trigger ratio and aims for the target ratio. Task output budgets and provider windows remain on their owner pages.")}
          paths={["context.compression_trigger_ratio", "context.compression_target_ratio"]}
          overrides={{
            "context.compression_trigger_ratio": { min: 0, max: 1, slider: { min: 0, max: 1, step: 0.01 } },
            "context.compression_target_ratio": { min: 0, max: 1, slider: { min: 0, max: 1, step: 0.01 } },
          }}
        />
      </SettingsDisclosure>
      <RelatedContextLinks />
    </SettingsPageBody>
  );
}

function RelatedContextLinks() {
  const navigateTo = useSettingsUiStore((state) => state.navigateTo);
  const links: readonly [string, string, SettingsPageId][] = [
    ["Home / Memory", "Resource reads, documents and rebuildable search caches.", "home" as const],
    ["Workspace", "Read, write, analysis and image boundaries.", "workspace" as const],
    ["Retrieval", "Candidate input, snapshot and page budgets.", "search-policies" as const],
    ["Task and model limits", "LLM output budgets and provider windows remain owner facts.", "llm-tasks" as const],
  ];
  return (
    <SectionCard title={settingsText("Related owner limits")} description={settingsText("These limits affect context inputs or results but remain editable by their owning module.")}>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {links.map(([title, detail, page]) => (
          <button key={title} type="button" className="group rounded-md border border-line bg-bg-sunken px-3 py-2 text-left hover:border-line-strong" onClick={() => navigateTo(page)}>
            <div className="flex items-center justify-between gap-2 text-[12px] font-medium text-fg"><span>{settingsText(title)}</span><span className="text-accent">→</span></div>
            <div className="mt-0.5 text-[11px] leading-4 text-fg-muted">{settingsText(detail)}</div>
          </button>
        ))}
      </div>
    </SectionCard>
  );
}

function ContextUsageCard() {
  const clients = useConnectionStore((s) => s.clients);
  const epoch = useConnectionStore((s) => s.epoch);
  const liveTurnId = useConnectionStore(
    (s) => s.status?.runtime.active_turn_id ?? null,
  );
  const [boundTurnId, setBoundTurnId] = useState<string | null>(liveTurnId);
  const [overview, setOverview] = useState<ContextOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { closed, stale, markFresh } = useTurnActivity(
    boundTurnId ?? "__no_context_turn__",
  );

  useEffect(() => {
    if (liveTurnId === null || liveTurnId === boundTurnId) return;
    setBoundTurnId(liveTurnId);
    setOverview(null);
    setError(null);
  }, [boundTurnId, liveTurnId]);

  const refresh = useCallback(() => {
    if (
      clients === null ||
      boundTurnId === null ||
      closed
    ) {
      return;
    }
    setLoading(true);
    void Promise.resolve()
      .then(() => requestIdForTurn(boundTurnId))
      .then((requestId) => contextClients(epoch).context.overview(requestId))
      .then((next) => {
        setOverview(next);
        setError(null);
        markFresh();
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      )
      .finally(() => setLoading(false));
  }, [boundTurnId, clients, closed, epoch, markFresh]);

  useEffect(() => {
    if (boundTurnId !== null && liveTurnId === boundTurnId) refresh();
    // The overview is read once for a bound Turn; later installs are exposed
    // through the stale marker and an explicit refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boundTurnId, epoch]);

  const chars = overview?.segments.reduce((sum, segment) => sum + segment.chars, 0) ?? 0;
  const imageBytes = overview?.segments.reduce((sum, segment) => sum + segment.image_bytes, 0) ?? 0;
  const slotRows = slotUsage(overview);
  return (
    <div className="space-y-2">
      {overview !== null && closed && <ClosedBanner />}
      {overview !== null && !closed && stale && (
        <RefreshNotice onRefresh={refresh} refreshing={loading} />
      )}
      <SectionCard
        title={settingsText("Current Context usage")}
        description={settingsText("Read-only installed segment sizes from the bound Turn; this is character and image-byte usage, not provider token accounting.")}
        actions={
          boundTurnId !== null && !closed ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 text-[11px] text-accent disabled:opacity-50"
              onClick={refresh}
              disabled={loading}
            >
              <RotateCw size={12} />
              {settingsText("Refresh")}
            </button>
          ) : undefined
        }
      >
        {overview ? (
          <>
            <div className="grid grid-cols-3 gap-2 text-[12px]">
              <UsageMetric label="Segments" value={String(overview.segments.length)} />
              <UsageMetric label="Characters" value={chars.toLocaleString()} />
              <UsageMetric label="Images" value={`${(imageBytes / (1024 * 1024)).toFixed(2)} MiB`} />
            </div>
            <div className="mt-3 divide-y divide-line rounded-md border border-line bg-bg-sunken">
              {slotRows.map((row) => (
                <div key={row.slot} className="flex items-center gap-3 px-3 py-2 text-[11px]">
                  <span className="w-20 shrink-0 font-semibold uppercase tracking-wide text-fg-muted">{row.slot}</span>
                  <span className="min-w-0 flex-1 text-fg-faint">{row.count} segments</span>
                  <span className="font-mono text-fg-muted">{row.chars.toLocaleString()} chars</span>
                  {row.imageBytes > 0 && <span className="font-mono text-fg-faint">{(row.imageBytes / (1024 * 1024)).toFixed(2)} MiB</span>}
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="text-[12px] text-fg-faint">
            {error ??
              (boundTurnId === null
                ? settingsText("No active Turn; the rail below shows the installed structure.")
                : settingsText("Reading the active Context…"))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

function slotUsage(overview: ContextOverview | null): Array<{
  slot: string;
  count: number;
  chars: number;
  imageBytes: number;
}> {
  if (overview === null) return [];
  const rows = new Map<string, { count: number; chars: number; imageBytes: number; order: number }>();
  for (const [index, segment] of overview.segments.entries()) {
    const current = rows.get(segment.slot) ?? { count: 0, chars: 0, imageBytes: 0, order: segment.order || index };
    current.count += 1;
    current.chars += segment.chars;
    current.imageBytes += segment.image_bytes;
    current.order = Math.min(current.order, segment.order || index);
    rows.set(segment.slot, current);
  }
  return [...rows.entries()]
    .sort(([, left], [, right]) => left.order - right.order)
    .map(([slot, row]) => ({ slot, ...row }));
}

function UsageMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-line bg-bg-sunken px-2.5 py-2"><div className="text-[10px] tracking-wide text-fg-faint uppercase">{label}</div><div className="mt-0.5 font-mono text-[13px] text-fg">{value}</div></div>;
}
