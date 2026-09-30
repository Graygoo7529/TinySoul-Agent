/**
 * Semantic UI components for trace/status display.
 *
 * Restored from baseline (c479ca0).
 */

export function TurnStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "answered":
      return <Badge tone="green">answered</Badge>;
    case "running":
      return (
        <Badge tone="accent">
          <span className="animate-pulse-dot">●</span> running
        </Badge>
      );
    case "waiting_question":
      return <Badge tone="yellow">waiting</Badge>;
    case "waiting_budget":
      return <Badge tone="yellow">waiting</Badge>;
    case "stopped":
      return <Badge tone="yellow">stopped</Badge>;
    case "cancelled":
      return <Badge tone="gray">cancelled</Badge>;
    case "failed":
      return <Badge tone="red">failed</Badge>;
    default:
      return <Badge tone="gray">{status}</Badge>;
  }
}

type BadgeTone = "green" | "red" | "yellow" | "gray" | "accent";

function Badge({ tone, children }: { tone: BadgeTone; children: React.ReactNode }) {
  const toneClasses: Record<BadgeTone, string> = {
    green: "bg-success-soft text-success",
    red: "bg-danger-soft text-danger",
    yellow: "bg-warning-soft text-warning",
    gray: "bg-fg-faint/10 text-fg-faint",
    accent: "bg-accent-soft text-accent",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}
