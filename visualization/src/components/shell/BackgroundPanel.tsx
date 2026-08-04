import { useMemo } from "react";
import { X } from "lucide-react";
import { selectTopLinks, useAppStore } from "../../store/appStore";
import { IconButton } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { Collapsible } from "../ui/Collapsible";
import { EmptyState } from "../ui/EmptyState";
import { Markdown } from "../markdown/Markdown";
import { LinkChip } from "../trace/semantic";

/**
 * Right slide-over showing the current BackgroundContext: the top-level
 * links loaded into the model's background, with their full content.
 */
export function BackgroundPanel() {
  const open = useAppStore((s) => s.backgroundOpen);
  const setOpen = useAppStore((s) => s.setBackgroundOpen);
  const events = useAppStore((s) => s.events);
  const links = useMemo(() => selectTopLinks(events), [events]);

  if (!open) return null;

  return (
    <aside className="animate-slide-in-right fixed inset-y-0 right-0 z-40 flex w-[min(460px,90vw)] flex-col border-l border-line bg-bg shadow-(--shadow-pop)">
      <div className="flex items-center gap-2 border-b border-line bg-bg-elev px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Background Context</div>
          <div className="text-[11px] text-fg-faint">
            {links.length} top-level link{links.length === 1 ? "" : "s"} currently loaded
          </div>
        </div>
        <IconButton label="Close" onClick={() => setOpen(false)}>
          <X size={15} />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {links.length === 0 && (
          <EmptyState
            title="No background loaded"
            description="Top-level home, memory and session entries appear here once the agent loads them into the background context."
          />
        )}
        {links.map((entry) => (
          <Collapsible
            key={entry.link}
            title={<LinkChip link={entry.link} />}
            meta={
              <>
                <Badge tone="gray">{entry.source}</Badge>
                {entry.evictable && <Badge tone="yellow">evictable</Badge>}
              </>
            }
          >
            <div className="max-h-[50vh] overflow-y-auto">
              <Markdown className="text-[12.5px]">{entry.content}</Markdown>
            </div>
          </Collapsible>
        ))}
      </div>
    </aside>
  );
}
