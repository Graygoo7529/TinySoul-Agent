/**
 * Home overlay changes (left panel, plan §11): the read-only create/modify/
 * delete entries the runs proposed. Selecting one opens its actual →
 * effective diff in the center. Review is the Home reflection's job — this
 * list never offers accept/reject.
 */

import type { ReactElement } from "react";
import { GitCompareArrows, Loader2, RotateCcw } from "lucide-react";

import type { JsonValue } from "../../api/v2/json";
import type { PageEnvelope } from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useConnectionStore } from "../../store/connectionStore";
import { usePagedSequence } from "../history/usePagedSequence";
import { useHomePage } from "./store";

export interface HomeChangeEntry {
  ref: string;
  kind: string;
  baselineDiverged: boolean;
}

/** Decode one changes item; null when the shape is not a change entry. */
export function decodeHomeChange(value: JsonValue): HomeChangeEntry | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const ref = typeof record.ref === "string" ? record.ref : null;
  const kind = typeof record.kind === "string" ? record.kind : null;
  if (ref === null || kind === null) return null;
  return {
    ref,
    kind,
    baselineDiverged: record.baseline_diverged === true,
  };
}

const KIND_TONES: Record<string, BadgeTone> = {
  created: "green",
  modified: "yellow",
  deleted: "red",
};

export function HomeChanges({ epoch }: { epoch: number }): ReactElement {
  const diffLink = useHomePage((s) => s.diffLink);
  const changes = usePagedSequence<JsonValue, PageEnvelope>(
    (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.home.changes(
        { continuation: token ?? undefined, limit: 100 },
        { signal },
      );
    },
    nextContinuation,
    [epoch],
  );

  const entries = changes.items
    .map(decodeHomeChange)
    .filter((entry): entry is HomeChangeEntry => entry !== null);

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-line bg-bg-elev/40">
      <div className="border-b border-line px-3 py-2 text-[11px] leading-4.5 text-fg-faint">
        Overlay changes proposed by runs, waiting for a Home reflection's
        review. Read-only here.
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
        {changes.loading ? (
          <div className="flex items-center gap-2 px-2 py-3 text-[12px] text-fg-faint">
            <Loader2 size={13} className="animate-spin-slow" />
            Reading overlay changes…
          </div>
        ) : changes.error !== null && entries.length === 0 ? (
          <EmptyState
            title="The changes could not be read"
            description={String(changes.error)}
            action={
              <Button variant="outline" size="sm" onClick={changes.reload}>
                <RotateCcw size={13} />
                Retry
              </Button>
            }
          />
        ) : entries.length === 0 ? (
          <EmptyState
            icon={<GitCompareArrows size={22} />}
            title="No overlay changes"
            description="Effective Home currently matches the accepted baseline."
          />
        ) : (
          <div className="space-y-1">
            {entries.map((entry) => (
              <button
                key={entry.ref}
                type="button"
                onClick={() =>
                  useHomePage.getState().openDiff(entry.ref, entry.kind)
                }
                title={entry.ref}
                className={`flex w-full items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-left ${
                  diffLink === entry.ref
                    ? "border-accent/50 bg-accent-soft"
                    : "border-line bg-bg-elev hover:border-line-strong"
                }`}
              >
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg">
                  {entry.ref.replace(/^home:/, "")}
                </span>
                <Badge tone={KIND_TONES[entry.kind] ?? "gray"}>{entry.kind}</Badge>
                {entry.baselineDiverged && (
                  <Badge tone="orange" title="The actual baseline changed since this overlay change was recorded">
                    diverged
                  </Badge>
                )}
              </button>
            ))}
            {changes.next !== null && (
              <Button
                variant="outline"
                size="xs"
                className="w-full"
                loading={changes.loadingMore}
                onClick={changes.loadMore}
              >
                Show more
              </Button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
