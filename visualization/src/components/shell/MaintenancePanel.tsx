import { useState } from "react";
import {
  CheckCircle2,
  ChevronRight,
  Home,
  MemoryStick,
  RefreshCcw,
} from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { maintenanceTaskCount } from "../../derive/maintenance";
import type { MaintenanceRequest } from "../../types";
import { randomId } from "../../utils/randomId";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

/**
 * Maintenance dialog. The persisted availability projection leads: when
 * nothing is pending the manual commands stay collapsed behind a disclosure;
 * when something is pending the relevant action is presented directly.
 */
export function MaintenancePanel() {
  const open = useAppStore((s) => s.maintenanceOpen);
  const setOpen = useAppStore((s) => s.setMaintenanceOpen);
  const client = useAppStore((s) => s.client);
  const maintenance = useAppStore((s) => s.maintenanceStatus);
  const pushToast = useAppStore((s) => s.pushToast);
  const [targetDay, setTargetDay] = useState("");
  const [rebuild, setRebuild] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);

  if (!open) return null;
  const availability = maintenance?.availability;
  const homePending = availability?.home_pending ?? false;
  const memoryPending = availability?.memory_pending ?? false;
  const anyPending = homePending || memoryPending;
  const pendingCount = maintenanceTaskCount(maintenance);

  const run = async (
    request: MaintenanceRequest,
    busyKey: string,
    label: string,
  ) => {
    if (!client) return;
    setBusy(busyKey);
    try {
      await client.requestMaintenance({
        ...request,
        command_id: randomId(),
      });
      pushToast("success", `${label} maintenance requested.`);
      setOpen(false);
    } catch (error) {
      pushToast(
        "error",
        `Maintenance request failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      title={anyPending ? `Maintenance available (${pendingCount})` : "Maintenance"}
      onClose={() => setOpen(false)}
    >
      <div className="space-y-3">
        {/* availability */}
        {!anyPending ? (
          <div className="flex items-center gap-2.5 rounded-lg bg-success-soft px-3 py-2.5 text-[13px] text-success">
            <CheckCircle2 size={15} className="shrink-0" />
            Everything is up to date — no maintenance is pending.
          </div>
        ) : (
          <div className="space-y-2">
            {homePending && (
              <div className="space-y-1.5">
                <div className="text-[11px] font-semibold text-fg-muted">Home</div>
                <PendingRow
                  icon={<Home size={14} />}
                  text={`${formatCount(availability!.home_change_count, "change")} · ${formatCount(availability!.home_skill_memory_count, "skill memory")}`}
                  action={
                    <Button
                      size="xs"
                      variant="primary"
                      className="w-full"
                      loading={busy === "home"}
                      onClick={() => void run({ kind: "home" }, "home", "Home")}
                    >
                      Run Home
                    </Button>
                  }
                />
              </div>
            )}
            {memoryPending && (
              <div className="space-y-1.5">
                <div className="text-[11px] font-semibold text-fg-muted">Memory</div>
                {availability!.memory_days.map((day) => (
                  <PendingRow
                    key={day}
                    icon={<MemoryStick size={14} />}
                    text={day}
                    action={
                      <Button
                        size="xs"
                        variant="primary"
                        className="w-full"
                        loading={busy === `memory:${day}`}
                        onClick={() => void run(
                          { kind: "memory", target_day: day },
                          `memory:${day}`,
                          `Memory ${day}`,
                        )}
                      >
                        Run
                      </Button>
                    }
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* manual commands */}
        <div className="rounded-lg border border-line">
          <button
            onClick={() => setManualOpen(!manualOpen)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left"
          >
            <ChevronRight
              size={13}
              className={`text-fg-faint transition-transform ${manualOpen ? "rotate-90" : ""}`}
            />
            <span className="text-[13px] font-medium text-fg-muted">
              Manual maintenance commands
            </span>
          </button>
          {manualOpen && (
            <div className="space-y-2.5 border-t border-line px-3 py-3">
              <ManualRow
                icon={<RefreshCcw size={14} />}
                title="Daily maintenance"
                description="Roll over the day, maintain Home, and consolidate yesterday's Memory."
                busy={busy === "daily"}
                onRun={() => void run({ kind: "daily" }, "daily", "Daily")}
              />
              <ManualRow
                icon={<Home size={14} />}
                title="Home maintenance"
                description="Review the runtime home overlay and commit accepted changes."
                busy={busy === "home"}
                onRun={() => void run({ kind: "home" }, "home", "Home")}
              />
              <ManualRow
                icon={<MemoryStick size={14} />}
                title="Memory maintenance"
                description="Distill an archived day's session facts into long-term memory."
                busy={busy === "memory:manual"}
                disabled={!targetDay}
                onRun={() => void run(
                  {
                    kind: "memory",
                    target_day: targetDay,
                    rebuild_memory: rebuild,
                  },
                  "memory:manual",
                  `Memory ${targetDay}`,
                )}
                options={
                  <>
                    <input
                      type="date"
                      value={targetDay}
                      onChange={(e) => setTargetDay(e.target.value)}
                      className="h-6 w-36 rounded-md border border-line bg-bg-elev px-2 font-mono text-[11px] outline-none focus:border-accent"
                    />
                    <label className="flex items-center gap-1.5 text-[11px] text-fg-muted">
                      <input
                        type="checkbox"
                        checked={rebuild}
                        onChange={(e) => setRebuild(e.target.checked)}
                        className="accent-accent"
                      />
                      Rebuild existing
                    </label>
                  </>
                }
              />
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

function PendingRow({
  icon,
  text,
  action,
}: {
  icon: React.ReactNode;
  text: string;
  action: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg bg-warning-soft px-3 py-2.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-warning/15 text-warning">
        {icon}
      </span>
      <span className="min-w-0 flex-1 text-[12px] leading-4 text-fg">{text}</span>
      <span className="flex w-24 shrink-0 justify-end">{action}</span>
    </div>
  );
}

function ManualRow({
  icon,
  title,
  description,
  busy,
  disabled = false,
  onRun,
  options,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  busy: boolean;
  disabled?: boolean;
  onRun: () => void;
  options?: React.ReactNode;
}) {
  return (
    <div className={`flex gap-2.5 ${options ? "" : "items-center"}`}>
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2.5">
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-medium">{title}</div>
            <div className="text-[11px] leading-4 text-fg-muted">{description}</div>
          </div>
          <span className="flex w-24 shrink-0 justify-end">
            <Button
              size="xs"
              variant="outline"
              loading={busy}
              disabled={disabled}
              onClick={onRun}
              className="w-full"
            >
              Run
            </Button>
          </span>
        </div>
        {options && (
          <div className="mt-1.5 flex items-center gap-3">{options}</div>
        )}
      </div>
    </div>
  );
}

function formatCount(value: number, noun: string): string {
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}
