import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

export function SettingsDisclosureSection({
  title,
  meta,
  children,
  defaultOpen = false,
}: {
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border-t border-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 bg-bg-sunken/20 px-5 py-3 text-left transition-colors hover:bg-hover"
      >
        <ChevronRight
          size={14}
          className={`shrink-0 text-fg-faint transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-fg">
          {title}
        </span>
        {meta && <span className="flex shrink-0 items-center gap-1.5">{meta}</span>}
      </button>
      {open && <div className="border-t border-line">{children}</div>}
    </section>
  );
}
