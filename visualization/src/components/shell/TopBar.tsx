import { Layers, RefreshCw, Wrench } from "lucide-react";
import { useAppStore } from "../../store/appStore";
import { maintenanceTaskCount } from "../../derive/maintenance";
import { Button, IconButton } from "../ui/Button";
import { Badge } from "../ui/Badge";

/**
 * The top bar: product title, the "turn active" badge, entry points for
 * Maintenance and the Background Context drawer, and the reconnect
 * indicator shown while the connection is down.
 */
export function TopBar() {
  const status = useAppStore((s) => s.status);
  const maintenanceStatus = useAppStore((s) => s.maintenanceStatus);
  const setMaintenanceOpen = useAppStore((s) => s.setMaintenanceOpen);
  const setBackgroundOpen = useAppStore((s) => s.setBackgroundOpen);
  const connected = useAppStore((s) => s.connection.status === "connected");

  const maintenancePending =
    maintenanceStatus?.availability.home_pending ||
    maintenanceStatus?.availability.memory_pending;
  const maintenanceCount = maintenanceTaskCount(maintenanceStatus);

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-bg-elev px-4">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">TinySoul</div>
      </div>
      {status?.turn_active && (
        <Badge tone="accent">
          <span className="animate-pulse-dot">●</span> turn active
        </Badge>
      )}
      <Button
        variant={maintenancePending ? "primary" : "ghost"}
        size="xs"
        onClick={() => setMaintenanceOpen(true)}
        disabled={!connected}
      >
        <Wrench size={12} />
        {maintenancePending
          ? `Maintenance available (${maintenanceCount})`
          : "Maintenance"}
      </Button>
      <IconButton
        label="Background context"
        onClick={() => setBackgroundOpen(true)}
        disabled={!connected}
      >
        <Layers size={15} />
      </IconButton>
      <ReconnectIndicator />
    </header>
  );
}

function ReconnectIndicator() {
  const connection = useAppStore((s) => s.connection);
  if (connection.status === "connected") return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-fg-faint">
      <RefreshCw size={12} className="animate-spin-slow" />
      {connection.status === "connecting" || connection.status === "initializing"
        ? "connecting…"
        : "disconnected"}
    </span>
  );
}
