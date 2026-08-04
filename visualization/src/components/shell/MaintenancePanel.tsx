import { useState } from "react";
import { Home, MemoryStick, RefreshCcw } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { randomId } from "../../utils/randomId";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

/**
 * Maintenance trigger dialog. Daily archive, Home and Memory maintenance are
 * Program-level work dispatched through the Endpoint; this dialog only
 * submits requests.
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

  if (!open) return null;
  const availability = maintenance?.availability;

  const run = async (kind: "daily" | "home" | "memory") => {
    if (!client) return;
    setBusy(kind);
    try {
      await client.requestMaintenance({
        kind,
        command_id: randomId(),
        target_day: kind === "memory" && targetDay ? targetDay : undefined,
        rebuild_memory: kind === "memory" ? rebuild : undefined,
      });
      pushToast("success", `${kind} maintenance requested.`);
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
    <Modal title="Maintenance" onClose={() => setOpen(false)}>
      <div className="space-y-3">
        {availability && (
          <div className="rounded-lg bg-bg-sunken px-3 py-2 text-[12px] text-fg-muted">
            {availability.home_pending
              ? `Home maintenance pending: ${availability.home_change_count} changes, ${availability.home_skill_memory_count} skill memories.`
              : "Home is up to date."}{" "}
            {availability.memory_pending
              ? `Memory pending for ${availability.memory_days.length} day(s): ${availability.memory_days.join(", ")}.`
              : "No pending memory days."}
          </div>
        )}

        <MaintenanceRow
          icon={<RefreshCcw size={15} />}
          title="Daily transition"
          description="Archive the previous business day (session, workspace, trash) and initialize the current day."
          action={
            <Button size="xs" variant="outline" loading={busy === "daily"} onClick={() => void run("daily")}>
              Run
            </Button>
          }
        />
        <MaintenanceRow
          icon={<Home size={15} />}
          title="Home maintenance"
          description="Review the runtime home overlay and commit accepted changes into the actual Agent Home."
          action={
            <Button size="xs" variant="outline" loading={busy === "home"} onClick={() => void run("home")}>
              Run
            </Button>
          }
        />
        <div className="rounded-lg border border-line px-3 py-2.5">
          <MaintenanceRow
            icon={<MemoryStick size={15} />}
            title="Memory maintenance"
            description="Distill an archived day's session facts into a long-term memory document."
            action={
              <Button size="xs" variant="outline" loading={busy === "memory"} onClick={() => void run("memory")}>
                Run
              </Button>
            }
          />
          <div className="mt-2 flex items-center gap-3 border-t border-line pt-2">
            <input
              value={targetDay}
              onChange={(e) => setTargetDay(e.target.value)}
              placeholder="YYYY-MM-DD (optional)"
              className="h-7 w-40 rounded-md border border-line bg-bg-elev px-2 font-mono text-[12px] outline-none focus:border-accent"
            />
            <label className="flex items-center gap-1.5 text-[12px] text-fg-muted">
              <input
                type="checkbox"
                checked={rebuild}
                onChange={(e) => setRebuild(e.target.checked)}
                className="accent-accent"
              />
              Rebuild existing memory
            </label>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function MaintenanceRow({
  icon,
  title,
  description,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium">{title}</div>
        <div className="text-[11px] leading-4 text-fg-muted">{description}</div>
      </div>
      {action}
    </div>
  );
}
