import type { ReactNode } from "react";

export type BadgeTone =
  | "gray"
  | "green"
  | "red"
  | "yellow"
  | "blue"
  | "accent"
  | "purple"
  | "teal"
  | "orange"
  | "pink";

const toneClasses: Record<BadgeTone, string> = {
  gray: "bg-hover text-fg-muted",
  green: "bg-success-soft text-success",
  red: "bg-danger-soft text-danger",
  yellow: "bg-warning-soft text-warning",
  blue: "bg-info-soft text-info",
  accent: "bg-accent-soft text-accent",
  purple: "bg-domain-home-soft text-domain-home",
  teal: "bg-domain-web-soft text-domain-web",
  orange: "bg-domain-execution-soft text-domain-execution",
  pink: "bg-domain-memory-soft text-domain-memory",
};

export function Badge({
  tone = "gray",
  children,
  className = "",
  title,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ${toneClasses[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
