import { BookOpen } from "lucide-react";

import { useAppStore, selectTopLinks } from "../store/appStore";

export function TopLinkPanel() {
  const { events, selectedTopLink, setSelectedTopLink } = useAppStore();
  const links = selectTopLinks(events);

  return (
    <div className="panel h-full">
      <div className="panel-header">
        <span className="flex items-center gap-2">
          <BookOpen size={14} />
          Top Links
          <span className="badge badge-normal">{links.length}</span>
        </span>
      </div>
      <div className="panel-body toplink-list">
        {links.length === 0 && (
          <div className="text-muted text-xs">No top-level background links loaded yet.</div>
        )}
        {links.map((entry) => {
          const isOpen = selectedTopLink === entry.link;
          return (
            <div key={entry.link} className={`toplink-item ${isOpen ? "active" : ""}`}>
              <div className="toplink-header" onClick={() => setSelectedTopLink(isOpen ? null : entry.link)}>
                <span className="toplink-link truncate">{entry.link}</span>
                <span className="badge badge-normal">{entry.owner}</span>
              </div>
              {isOpen && (
                <div className="toplink-content">
                  <div className="text-muted text-xs mb-2">
                    source: {entry.source} · evictable: {String(entry.evictable)}
                  </div>
                  {entry.content}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
