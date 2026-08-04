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
  purple: "bg-purple-500/10 text-purple-500 dark:text-purple-400",
  teal: "bg-teal-500/10 text-teal-600 dark:text-teal-400",
  orange: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  pink: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
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
