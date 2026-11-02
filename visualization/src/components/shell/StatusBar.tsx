import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";

/**
 * The bottom status bar: connection phase, backend readiness, the active
 * day, the current turn kind/state and the connected endpoint address.
 */
export function StatusBar() {
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
            ? "无响应…"
            : eventsPhase === "reconnecting"
              ? "重新连接中…"
              : "已连接"
          : phase === "idle"
            ? "未连接"
            : phase === "connecting"
              ? "连接中…"
              : phase === "error"
                ? "连接失败"
                : phase}
      </span>
      {connected && status && (
        <>
          <span className={status.ready ? "hidden text-fg-faint sm:inline" : "hidden text-warning sm:inline"}>
            {status.ready ? "就绪" : "启动中…"}
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
                ? "进行中"
                : "等待输入"}
          </span>
        </>
      )}
      <span className="ml-auto hidden font-mono text-fg-faint sm:inline">
        {info ? info.address.httpBaseUrl : "—"}
      </span>
    </footer>
  );
}
