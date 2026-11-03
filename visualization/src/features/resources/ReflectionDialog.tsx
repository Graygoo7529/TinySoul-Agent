import { t, useI18n, message, LocalizedText, type UiText } from "../../i18n";
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
 * queued the dialog says so; acceptance opens the corresponding Chat card.
 */

import { useEffect, useMemo, useState, type ReactElement } from "react";
import { AlertTriangle, CalendarClock, Loader2, Sparkles } from "lucide-react";

import type {
  ReflectionAvailability,
  ReflectionRequestBody,
} from "../../api/v2/types";
import { apiErrorCode } from "../../api/v2/errors";
import { Modal } from "../../components/ui/Modal";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { showRuntimeTurn } from "../chat/turnController";
import { useConnectionStore } from "../../store/connectionStore";
import { randomId } from "../../utils/randomId";

export interface ReflectionDialogProps {
  kind?: "home" | "memory";
  /**
   * Optional prefill for the instructions textarea (e.g. a focused review
   * note from the diff view). It is only the initial value — the user can
   * edit or clear it, and the submit path is unchanged.
   */
  initialInstructions?: string;
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

export function ReflectionDialog({ kind: initialKind, initialInstructions, onClose }: ReflectionDialogProps): ReactElement {
  useI18n();
  const [kind, setKind] = useState<"home" | "memory">(initialKind ?? "home");
  const [availability, setAvailability] = useState<ReflectionAvailability | null>(null);
  const [loadError, setLoadError] = useState<UiText | null>(null);
  const [earlierBusy, setEarlierBusy] = useState(false);
  const [targetDay, setTargetDay] = useState<string | null>(null);
  const [manualDay, setManualDay] = useState("");
  const [instructions, setInstructions] = useState(initialInstructions ?? "");
  const [submitError, setSubmitError] = useState<UiText | null>(null);
  const [busy, setBusy] = useState(false);

  const queueBusy = useConnectionStore(
    (s) =>
      (s.status?.runtime.active_turn_id ?? null) !== null ||
      (s.status?.runtime.queued_request_ids.length ?? 0) > 0,
  );

  useEffect(() => {
    const clients = useConnectionStore.getState().clients;
    if (clients === null) {
      setLoadError(message("connection.notConnected"));
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
    const { clients, epoch } = useConnectionStore.getState();
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
        if (useConnectionStore.getState().epoch !== epoch) return;
        void showRuntimeTurn(epoch, result.request_id);
        onClose();
      })
      .catch((error: unknown) => {
        setBusy(false);
        const code = apiErrorCode(error);
        if (code === "agent.queue_full") {
          setSubmitError(
            message("resources.reflectionQueueFull"),
          );
          return;
        }
        setSubmitError(error instanceof Error ? error.message : String(error));
      });
  };

  const title = kind === "home" ? t("home.organize") : t("memory.organize");

  return (
    <Modal title={title} onClose={onClose}>
        <div className="space-y-4">
          {!initialKind && <div className="flex gap-1 rounded-lg border border-line bg-bg-sunken p-1">
            {(["home", "memory"] as const).map((value) => <Button key={value} className="flex-1" size="sm"
              variant={kind === value ? "secondary" : "ghost"} disabled={busy}
              onClick={() => { setKind(value); setSubmitError(null); }}>{value === "home" ? t("shell.home") : t("shell.memory")}</Button>)}
          </div>}
          {queueBusy && (
            <div className="flex items-start gap-2 rounded-lg border border-line bg-bg-sunken px-3 py-2 text-[12px] text-fg-muted">
              <CalendarClock size={13} className="mt-0.5 shrink-0 text-fg-faint" />
{t("resources.reflectionQueued")}</div>
          )}

          {loadError !== null && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <LocalizedText value={loadError} />
            </div>
          )}

          {availability === null && loadError === null && (
            <p className="flex items-center gap-2 text-[12px] text-fg-faint">
              <Loader2 size={13} className="animate-spin-slow" />
              {t("resources.loadingReflection")}</p>
          )}

          {kind === "home" && availability !== null && (
            <p className="text-[13px] leading-5.5 text-fg-muted">
              {availability.home_change_count > 0 || availability.home_skill_memory_count > 0 ? (
                <>
                  {t("resources.pendingHomeReview", { count: availability.home_change_count })}
                </>
              ) : (
                <>
                  {t("resources.noHomeChanges")}</>
              )}
              {availability.home_skill_memory_count > 0 && <span className="block mt-1">{t("resources.pendingSkills", { count: availability.home_skill_memory_count })}</span>}
            </p>
          )}

          {kind === "memory" && availability !== null && (
            <section aria-label={t("resources.targetDay")} className="space-y-2">
              <h3 className="text-[12px] font-semibold text-fg">{t("resources.targetDay")}</h3>
              {candidates.length === 0 ? (
                <p className="text-[12px] text-fg-faint">
                  {t("resources.noSuggestedDay")}</p>
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
                        <Badge tone="yellow" title={t("resources.noDailyHint")}>
                          {t("resources.noDaily")}</Badge>
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
                  {t("resources.findEarlier", { day: availability.next_before })}
                </Button>
              )}
              <label className="flex items-center gap-2 text-[12px] text-fg-muted">
                <span className="shrink-0">{t("resources.specificDay")}</span>
                <input
                  type="date"
                  value={manualDay}
                  onChange={(event) => setManualDay(event.target.value)}
                  aria-label={t("resources.customDay")}
                  className="h-7 rounded-lg border border-line bg-bg-elev px-2 font-mono text-[11.5px] outline-none focus:border-accent"
                />
              </label>
            </section>
          )}

          <section aria-label={t("resources.instructions")} className="space-y-1.5">
            <h3 className="text-[12px] font-semibold text-fg">
              {t("resources.instructions")}</h3>
            <textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              rows={4}
              maxLength={16000}
              placeholder={
                kind === "home"
                  ? t("resources.homeReflectionPlaceholder")
                  : t("resources.memoryReflectionPlaceholder")
              }
              aria-label={t("resources.instructionInput")}
              className="w-full resize-y rounded-lg border border-line bg-bg-elev px-3 py-2 text-[13px] leading-5 outline-none focus:border-accent"
            />
          </section>

          {submitError !== null && (
            <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-[12px] text-danger">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <LocalizedText value={submitError} />
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t("runtime.cancel")}</Button>
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
              {kind === "home" ? t("resources.startHomeReflection") : t("resources.startMemoryReflection")}
            </Button>
          </div>
        </div>
    </Modal>
  );
}
