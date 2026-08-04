import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {icon && <div className="mb-1 text-fg-faint">{icon}</div>}
      <div className="text-sm font-medium text-fg-muted">{title}</div>
      {description && (
        <div className="max-w-sm text-xs leading-5 text-fg-faint">{description}</div>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
