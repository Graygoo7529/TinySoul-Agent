/**
 * The shared "organize" dialog (plan §11/§12, API-04).
 *
 * One explicit grant per submit: Home asks for kind=home with instructions
 * only — no target-day control (that belongs to Memory); Memory requires an
 * explicit source day. The suggested days come from the owner availability
 * projection (missing daily first, then any day that may be organized again);
 * `next_before` pages further back instead of treating the first page as the
 * whole archive. A day without a daily is a clue, never an authorization, and
 * a day that already has a daily stays selectable.
 *
 * The Reflection shares the root queue: when other root work is active or
 * queued the dialog says so, and the receipt view leads to the runtime page.
 */

import { useEffect, useMemo, useState, type ReactElement } from "react";
import { AlertTriangle, CalendarClock, Loader2, Sparkles } from "lucide-react";

import type {
  ReflectionAvailability,
  ReflectionRequestBody,
  TurnCreateReceipt,
} from "../../api/v2/types";
import { apiErrorCode } from "../../api/v2/errors";
import { Modal } from "../../components/ui/Modal";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { randomId } from "../../utils/randomId";

export interface ReflectionDialogProps {
  kind: "home" | "memory";
  onClose: () => void;
}

interface DayCandidate {
  day: string;
  /** True when the day has no persistent daily yet (a clue, not a grant). */
  missingDaily: boolean;
}

/** Merge availability pages into descending-unique candidates. */
export function mergeDayCandidates(
  memoryDays: string[],
  missingDailyDays: string[],
): DayCandidate[] {
  const missing = new Set(missingDailyDays);
  const all = new Set([...memoryDays, ...missingDailyDays]);
  return [...all].sort((a, b) => (a < b ? 1 : -1)).map((day) => ({
    day,
    missingDaily: missing.has(day),
  }));
}

/** The default suggestion: a day without a daily first, else the most recent. */
export function suggestedTargetDay(candidates: DayCandidate[]): string | null {
  return candidates.find((candidate) => candidate.missingDaily)?.day ??
    candidates[0]?.day ??
    null;
}

export function ReflectionDialog({ kind, onClose }: ReflectionDialogProps): ReactElement {
  const [availability, setAvailability] = useState<ReflectionAvailability | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [earlierBusy, setEarlierBusy] = useState(false);
  const [targetDay, setTargetDay] = useState<string | null>(null);
  const [manualDay, setManualDay] = useState("");
  const [instructions, setInstructions] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<TurnCreateReceipt | null>(null);

  const queueBusy = useConnectionStore(
    (s) =>
      (s.status?.runtime.active_turn_id ?? null) !== null ||
      (s.status?.runtime.queued_turn_ids.length ?? 0) > 0,
  );

  useEffect(() => {
    const clients = useConnectionStore.getState().clients;
    if (clients === null) {
      setLoadError("Not connected to a backend.");
      return;
    }
    const controller = new AbortController();
    clients.reflection
      .availability(undefined, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setAvailability(response.availability);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, []);

  const candidates = useMemo<DayCandidate[]>(
    () =>
      availability === null
        ? []
        : mergeDayCandidates(availability.memory_days, availability.missing_daily_days),
    [availability],
  );

  // The default suggestion lands once availability arrives; the user may
  // always override it — it is never forced to the current execution day.
  useEffect(() => {
    if (kind !== "memory" || availability === null) return;
    setTargetDay((current) => current ?? suggestedTargetDay(candidates));
  }, [kind, availability, candidates]);

  const loadEarlier = () => {
    const clients = useConnectionStore.getState().clients;
    const before = availability?.next_before ?? null;
    if (clients === null || before === null || earlierBusy) return;
    setEarlierBusy(true);
    clients.reflection
      .availability({ before })
      .then((response) => {
        setAvailability((current) =>
          current === null
            ? response.availability
            : {
                ...response.availability,
                memory_days: [
                  ...current.memory_days,
                  ...response.availability.memory_days.filter(
                    (day) => !current.memory_days.includes(day),
                  ),
                ],
                missing_daily_days: [
                  ...current.missing_daily_days,
                  ...response.availability.missing_daily_days.filter(
                    (day) => !current.missing_daily_days.includes(day),
                  ),
                ],
                scanned_days: current.scanned_days + response.availability.scanned_days,
              },
        );
        setEarlierBusy(false);
      })
      .catch((error: unknown) => {
        setEarlierBusy(false);
        setLoadError(error instanceof Error ? error.message : String(error));
      });
  };

  const effectiveTargetDay = manualDay.trim() !== "" ? manualDay.trim() : targetDay;

  const submit = () => {
    const clients = useConnectionStore.getState().clients;
    if (clients === null || busy) return;
    if (kind === "memory" && effectiveTargetDay === null) return;
    setBusy(true);
    setSubmitError(null);
    const body: ReflectionRequestBody =
      kind === "home"
        ? {
            kind: "home",
            instructions: instructions.trim() || undefined,
            command_id: `reflect-${randomId()}`,
          }
        : {
            kind: "memory",
            target_day: effectiveTargetDay!,
            instructions: instructions.trim() || undefined,
            command_id: `reflect-${randomId()}`,
          };
    clients.reflection
      .request(body)
      .then((result) => {
        setBusy(false);
        setReceipt(result);
      })
      .catch((error: unknown) => {
        setBusy(false);
        const code = apiErrorCode(error);
        if (code === "agent.queue_full") {
          setSubmitError(
            "The root queue is full right now — your request was not queued. The instructions are kept; try again in a moment.",
          );
          return;
        }
        setSubmitError(error instanceof Error ? error.message : String(error));
      });
  };

  const openRuntime = () => {
    useAppStore.getState().setActiveTab("runtime");
    onClose();
  };

  const title = kind === "home" ? "Organize Home" : "Organize Memory";

  return (
    <Modal title={title} onClose={onClose}>
      {receipt !== null ? (
        <div className="space-y-3">
          <p className="text-[13px] text-fg-muted">
            The {kind === "home" ? "Home" : "Memory"} reflection was accepted
            {kind === "memory" && effectiveTargetDay !== null && (
              <>
                {" "}for source day{" "}
                <span className="font-mono text-[12px]">{effectiveTargetDay}</span>
              </>
            )}
            . It runs as its own turn on the shared root queue.
          </p>
          <p className="font-mono text-[11px] text-fg-faint">turn: {receipt.turn_id}</p>
          <div className="flex items-center gap-2 pt-1">
            <Button variant="primary" size="sm" onClick={openRuntime}>
              Open runtime view
            </Button>
            <Button variant="outline" size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {queueBusy && (
            <div className="flex items-start gap-2 rounded-lg border border-line bg-bg-sunken px-3 py-2 text-[12px] text-fg-muted">
              <CalendarClock size={13} className="mt-0.5 shrink-0 text-fg-faint" />
              Other root work is active or queued — this reflection queues
              behind it and runs when the queue reaches it.
            </div>
          )}

          {loadError !== null && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              {loadError}
            </div>
          )}

          {availability === null && loadError === null && (
            <p className="flex items-center gap-2 text-[12px] text-fg-faint">
              <Loader2 size={13} className="animate-spin-slow" />
              Reading what can be organized…
            </p>
          )}

          {kind === "home" && availability !== null && (
            <p className="text-[13px] leading-5.5 text-fg-muted">
              {availability.home_change_count > 0 ? (
                <>
                  {availability.home_change_count} overlay{" "}
                  {availability.home_change_count === 1 ? "change" : "changes"}{" "}
                  pending review. A Home reflection decides what becomes the
                  accepted baseline — the page itself never accepts or rejects.
                </>
              ) : (
                <>
                  No overlay changes are pending. A Home reflection can still
                  tidy and reorganize the accepted content.
                </>
              )}
            </p>
          )}

          {kind === "memory" && availability !== null && (
            <section aria-label="Target day" className="space-y-2">
              <h3 className="text-[12px] font-semibold text-fg">Target day</h3>
              {candidates.length === 0 ? (
                <p className="text-[12px] text-fg-faint">
                  No source days were suggested from the scanned days.
                </p>
              ) : (
                <div className="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-line bg-bg-sunken p-1.5">
                  {candidates.map((candidate) => (
                    <label
                      key={candidate.day}
                      className={`flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] ${
                        effectiveTargetDay === candidate.day && manualDay.trim() === ""
                          ? "bg-accent-soft text-accent"
                          : "text-fg-muted hover:bg-hover"
                      }`}
                    >
                      <input
                        type="radio"
                        name="reflection-target-day"
                        checked={
                          manualDay.trim() === "" && targetDay === candidate.day
                        }
                        onChange={() => {
                          setManualDay("");
                          setTargetDay(candidate.day);
                        }}
                        className="accent-accent"
                      />
                      <span className="font-mono text-[11.5px]">{candidate.day}</span>
                      {candidate.missingDaily && (
                        <Badge tone="yellow" title="This day has no persistent daily document yet — a clue, not an authorization">
                          no daily yet
                        </Badge>
                      )}
                    </label>
                  ))}
                </div>
              )}
              {availability.next_before !== null && (
                <Button
                  variant="ghost"
                  size="xs"
                  loading={earlierBusy}
                  onClick={loadEarlier}
                >
                  Look further back (before {availability.next_before})
                </Button>
              )}
              <label className="flex items-center gap-2 text-[12px] text-fg-muted">
                <span className="shrink-0">Or pick a day:</span>
                <input
                  type="date"
                  value={manualDay}
                  onChange={(event) => setManualDay(event.target.value)}
                  aria-label="Custom target day"
                  className="h-7 rounded-lg border border-line bg-bg-elev px-2 font-mono text-[11.5px] outline-none focus:border-accent"
                />
              </label>
            </section>
          )}

          <section aria-label="Instructions" className="space-y-1.5">
            <h3 className="text-[12px] font-semibold text-fg">
              This run's instructions
            </h3>
            <textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              rows={4}
              placeholder={
                kind === "home"
                  ? "What to focus on while reviewing Home…"
                  : "What this day should settle into persistent knowledge…"
              }
              aria-label="Reflection instructions"
              className="w-full resize-y rounded-lg border border-line bg-bg-elev px-3 py-2 text-[13px] leading-5 outline-none focus:border-accent"
            />
          </section>

          {submitError !== null && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              {submitError}
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={busy}
              disabled={
                availability === null ||
                (kind === "memory" && effectiveTargetDay === null)
              }
              onClick={submit}
            >
              <Sparkles size={13} />
              {kind === "home" ? "Start Home reflection" : "Start Memory reflection"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
