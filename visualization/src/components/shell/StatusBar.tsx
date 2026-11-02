import { tStatus, useI18n } from "../../i18n";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";

/**
 * The bottom status bar: connection phase, backend readiness, the active
 * day, the current turn kind/state and the connected endpoint address.
 */
export function StatusBar() {
  const { t } = useI18n();
  const phase = useConnectionStore((s) => s.phase);
  const eventsPhase = useConnectionStore((s) => s.eventsPhase);
  const unreachable = useConnectionStore((s) => s.unreachable);
  const status = useConnectionStore((s) => s.status);
  const info = useConnectionStore((s) => s.info);
  const snapshot = useTurnStore((s) => s.snapshot);

  const connected = phase === "connected";
  const degraded = unreachable || eventsPhase === "reconnecting";

  return (
    <footer className="flex h-7 shrink-0 items-center gap-3 overflow-hidden border-t border-line bg-bg-elev px-3 text-[11px] text-fg-muted tabular-nums whitespace-nowrap">
      <span className="flex shrink-0 items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            connected ? (degraded ? "bg-warning" : "bg-success") : "bg-danger"
          }`}
        />
        {connected
          ? unreachable
            ? t("connection.unreachable")
            : eventsPhase === "reconnecting"
              ? t("connection.reconnecting")
              : t("connection.connected")
          : phase === "idle"
            ? t("connection.notConnected")
            : phase === "connecting"
              ? t("connection.connecting")
              : phase === "error"
                ? t("connection.failed")
                : phase}
      </span>
      {connected && status && (
        <>
          <span className={status.ready ? "hidden text-fg-faint sm:inline" : "hidden text-warning sm:inline"}>
            {status.ready ? tStatus("ready") : tStatus("starting")}
          </span>
          <span className="hidden text-fg-faint sm:inline">{status.active_day}</span>
          <span
            className={`hidden sm:inline ${
              status.turn_active ? "text-accent" : "text-fg-faint"
            }`}
          >
            {snapshot !== null && status.turn_active
              ? `${snapshot.kind} turn · ${snapshot.state}`
              : status.turn_active
                ? t("shell.turnActive")
                : t("connection.waitingInput")}
          </span>
        </>
      )}
      <span className="ml-auto hidden font-mono text-fg-faint sm:inline">
        {info ? info.address.httpBaseUrl : "—"}
      </span>
    </footer>
  );
}
