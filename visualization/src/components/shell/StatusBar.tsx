import { useAppStore } from "../../store/appStore";

export function StatusBar() {
  const connection = useAppStore((s) => s.connection);
  const status = useAppStore((s) => s.status);
  const reconnecting = useAppStore((s) => s.streamReconnecting);
  const unreachable = useAppStore((s) => s.backendUnreachable);
  const connected = connection.status === "connected";

  return (
    <footer className="flex h-7 shrink-0 items-center gap-3 border-t border-line bg-bg-elev px-3 text-[11px] text-fg-muted">
      <span className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            connected
              ? unreachable || reconnecting
                ? "bg-warning"
                : "bg-success"
              : "bg-danger"
          }`}
        />
        {connected
          ? unreachable
            ? "not responding…"
            : reconnecting
              ? "reconnecting…"
              : "connected"
          : connection.status}
      </span>
      {status && (
        <>
          <span className="text-fg-faint">day {status.active_day}</span>
          <span className="text-fg-faint">workspace rev {status.workspace_revision}</span>
          <span className={status.turn_active ? "text-accent" : "text-fg-faint"}>
            {status.turn_active ? "turn active" : "waiting for input"}
          </span>
        </>
      )}
      <span className="ml-auto hidden font-mono text-fg-faint sm:inline">
        {connection.info ? `${connection.info.host}:${connection.info.port}` : "—"}
      </span>
    </footer>
  );
}
