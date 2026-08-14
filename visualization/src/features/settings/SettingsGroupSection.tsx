import type { ReactNode } from "react";

export function SettingsGroupSection({
  title,
  description,
  meta,
  children,
}: {
  title: string;
  description?: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-line first:border-t-0">
      <header className="flex items-start justify-between gap-4 border-b border-line bg-bg-sunken/40 px-5 py-3.5">
        <div className="min-w-0">
          <h3 className="text-[14px] font-semibold text-fg">{title}</h3>
          {description && (
            <p className="mt-1 max-w-3xl text-[11px] leading-4 text-fg-muted">
              {description}
            </p>
          )}
        </div>
        {meta && <div className="shrink-0 pt-0.5">{meta}</div>}
      </header>
      {children}
    </section>
  );
}
