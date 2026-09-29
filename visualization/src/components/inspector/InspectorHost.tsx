import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
  type UIEvent,
} from "react";
import { ArrowLeft, Check, Copy, Maximize2, Minimize2, X } from "lucide-react";
import { IconButton } from "../ui/Button";

/** Default drawer width; a per-entry `width` overrides it. */
export const INSPECTOR_DEFAULT_WIDTH = "min(640px, 94vw)";
/** Wide view: a larger share of the window for maps, diffs and dense detail. */
export const INSPECTOR_EXPANDED_WIDTH = "min(1120px, 96vw)";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * One level of detail in the inspector. The stack itself belongs to the
 * caller — push / replace / pop / reset are prop changes — while the host
 * renders the top entry and remembers each entry's scroll position.
 */
export interface InspectorEntry {
  /** Stable identity: drives scroll memory and focus-on-navigation. */
  key: string;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Real link/reference offered through a copy button; hidden when absent. */
  copyText?: string;
  /** Width used while this entry is on top and the wide view is collapsed. */
  width?: string;
  /** Body content, supplied by the caller. */
  render: () => ReactNode;
}

interface InspectorHostBaseProps {
  /** Back stack of detail entries; the top entry is visible. Empty = closed. */
  entries: InspectorEntry[];
  /** Back one level; only invoked while the stack holds more than one entry. */
  onPop: () => void;
  /** Close the whole inspector. */
  onClose: () => void;
  /**
   * Element that opened the inspector; focus returns to it on close. When
   * omitted, the element focused at open time is restored instead.
   */
  triggerRef?: RefObject<HTMLElement | null>;
  defaultWidth?: string;
  expandedWidth?: string;
}

export type InspectorHostProps = InspectorHostBaseProps &
  (
    | {
        /** Nested detail layered above the main drawer (sub-drawer). */
        sub: InspectorEntry;
        /** Close the sub-drawer and return to the main drawer. */
        onCloseSub: () => void;
      }
    | { sub?: null; onCloseSub?: () => void }
  );

/**
 * Shared detail drawer: a right-side glass panel hosting a caller-owned back
 * stack of entries. The top entry is visible; Back pops one level, Close
 * dismisses everything, a toggle expands a wide view, and a copy button
 * offers the entry's real link. Opening or drilling lands focus on the
 * detail title; closing returns focus to the trigger. Esc closes the
 * topmost layer and Tab is trapped inside the active layer. An optional
 * sub entry stacks a second panel above the drawer for nested detail such
 * as a model call opened from a context segment.
 */
export function InspectorHost(props: InspectorHostProps) {
  const {
    entries,
    onPop,
    onClose,
    triggerRef,
    defaultWidth = INSPECTOR_DEFAULT_WIDTH,
    expandedWidth = INSPECTOR_EXPANDED_WIDTH,
  } = props;
  const sub = props.sub ?? null;
  const onCloseSub = props.onCloseSub;

  const open = entries.length > 0;
  const top = open ? entries[entries.length - 1] : undefined;
  const topKey = top?.key ?? null;
  const subKey = sub?.key ?? null;

  const reduced = usePrefersReducedMotion();
  const [expanded, setExpanded] = useState(false);

  const mainTitleId = useId();
  const subTitleId = useId();
  const panelRef = useRef<HTMLElement | null>(null);
  const subPanelRef = useRef<HTMLElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  const subTitleRef = useRef<HTMLHeadingElement | null>(null);
  const scrollMemory = useRef(new Map<string, number>());
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const subRestoreFocusRef = useRef<HTMLElement | null>(null);
  const prevRef = useRef<{ open: boolean; topKey: string | null }>({
    open: false,
    topKey: null,
  });
  const prevSubKeyRef = useRef<string | null>(null);

  const width = expanded ? expandedWidth : (top?.width ?? defaultWidth);
  const subWidth = expanded ? expandedWidth : (sub?.width ?? width);
  const widthTransition = reduced
    ? undefined
    : "width 0.24s cubic-bezier(0.32, 0.72, 0, 1)";

  // Restore the remembered scroll position when another entry surfaces.
  useLayoutEffect(() => {
    const node = bodyRef.current;
    if (!open || !topKey || !node) return;
    node.scrollTop = scrollMemory.current.get(topKey) ?? 0;
  }, [open, topKey]);

  // Focus lifecycle of the main drawer: record the trigger on open, land on
  // the detail title on open/drill, hand focus back on close; the wide view
  // and the scroll memory reset once the drawer is closed.
  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = { open, topKey };
    if (!open) {
      if (prev.open) {
        const target = triggerRef?.current ?? restoreFocusRef.current;
        restoreFocusRef.current = null;
        if (target?.isConnected) target.focus();
      }
      scrollMemory.current.clear();
      setExpanded(false);
      return;
    }
    if (!prev.open) {
      restoreFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    if (topKey !== prev.topKey) titleRef.current?.focus();
  }, [open, topKey, triggerRef]);

  // Sub-drawer focus lifecycle, mirrored against the main drawer: opening
  // lands on its title, closing returns to the control that opened it.
  useEffect(() => {
    const prev = prevSubKeyRef.current;
    prevSubKeyRef.current = subKey;
    if (subKey) {
      if (prev === null) {
        subRestoreFocusRef.current =
          document.activeElement instanceof HTMLElement ? document.activeElement : null;
      }
      if (subKey !== prev) subTitleRef.current?.focus();
      return;
    }
    if (prev !== null) {
      const target = subRestoreFocusRef.current;
      subRestoreFocusRef.current = null;
      if (target?.isConnected) target.focus();
    }
  }, [subKey]);

  // Esc closes the topmost layer only; Tab cycles inside the active layer
  // (the sub-drawer while present, otherwise the main drawer).
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        if (sub && onCloseSub) onCloseSub();
        else if (entries.length > 1) onPop();
        else onClose();
        return;
      }
      if (event.key === "Tab") {
        const layer = sub ? subPanelRef.current : panelRef.current;
        if (layer) trapTab(event, layer);
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, sub, onCloseSub, entries.length, onPop, onClose]);

  const rememberScroll = (event: UIEvent<HTMLDivElement>) => {
    if (topKey) scrollMemory.current.set(topKey, event.currentTarget.scrollTop);
  };

  if (!open || !top) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-(--z-overlay) bg-black/25 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={mainTitleId}
        className={`glass-panel fixed inset-y-0 right-0 z-(--z-drawer) flex flex-col border-l border-line shadow-pop${reduced ? "" : " animate-slide-in-right"}`}
        style={{ width, transition: widthTransition }}
      >
        <PanelHeader
          entry={top}
          titleId={mainTitleId}
          titleRef={titleRef}
          onBack={entries.length > 1 ? onPop : undefined}
          expanded={expanded}
          onToggleExpand={() => setExpanded((value) => !value)}
          onClose={onClose}
        />
        <div
          ref={bodyRef}
          onScroll={rememberScroll}
          className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
        >
          <div key={top.key} className={reduced ? undefined : "animate-sub-drawer-in"}>
            {top.render()}
          </div>
        </div>
      </aside>

      {sub && onCloseSub && (
        <>
          <div
            className="fixed inset-0 z-(--z-subdrawer-overlay)"
            onClick={onCloseSub}
            aria-hidden="true"
          />
          <aside
            ref={subPanelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={subTitleId}
            className={`glass-panel fixed inset-y-0 right-0 z-(--z-subdrawer) flex flex-col border-l border-line shadow-pop${reduced ? "" : " animate-sub-drawer-in"}`}
            style={{ width: subWidth, transition: widthTransition }}
          >
            <PanelHeader
              entry={sub}
              titleId={subTitleId}
              titleRef={subTitleRef}
              onBack={onCloseSub}
              onClose={onClose}
            />
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              <div key={sub.key}>{sub.render()}</div>
            </div>
          </aside>
        </>
      )}
    </>
  );
}

function PanelHeader({
  entry,
  titleId,
  titleRef,
  onBack,
  expanded,
  onToggleExpand,
  onClose,
}: {
  entry: InspectorEntry;
  titleId: string;
  titleRef: RefObject<HTMLHeadingElement | null>;
  onBack?: () => void;
  expanded?: boolean;
  onToggleExpand?: () => void;
  onClose: () => void;
}) {
  return (
    <header className="flex items-center gap-1.5 border-b border-line bg-bg-elev px-3 py-2.5">
      {onBack && (
        <IconButton label="Back" onClick={onBack}>
          <ArrowLeft size={15} />
        </IconButton>
      )}
      <div className="min-w-0 flex-1 pl-1">
        <h2
          id={titleId}
          ref={titleRef}
          tabIndex={-1}
          className="truncate text-sm font-semibold outline-none"
        >
          {entry.title}
        </h2>
        {entry.subtitle && (
          <div className="mt-0.5 truncate text-[11px] text-fg-faint">{entry.subtitle}</div>
        )}
      </div>
      {entry.copyText && <CopyIconButton text={entry.copyText} />}
      {onToggleExpand && (
        <IconButton
          label={expanded ? "Collapse wide view" : "Expand wide view"}
          active={expanded}
          onClick={onToggleExpand}
        >
          {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </IconButton>
      )}
      <IconButton label="Close" onClick={onClose}>
        <X size={15} />
      </IconButton>
    </header>
  );
}

/** Copies the entry's real link/reference; briefly confirms with a check. */
function CopyIconButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <IconButton
      label={copied ? "Copied" : "Copy link"}
      onClick={() => {
        const write = navigator.clipboard?.writeText(text);
        if (write) {
          void write.then(
            () => setCopied(true),
            () => {},
          );
        }
      }}
    >
      {copied ? <Check size={15} className="text-success" /> : <Copy size={15} />}
    </IconButton>
  );
}

/** Keeps Tab / Shift+Tab cycling among the focusable controls of one layer. */
function trapTab(event: KeyboardEvent, layer: HTMLElement) {
  const items = Array.from(layer.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
  if (items.length === 0) {
    event.preventDefault();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  const inside = active instanceof HTMLElement && layer.contains(active);
  if (event.shiftKey ? inside && active !== first : inside && active !== last) return;
  event.preventDefault();
  (event.shiftKey ? last : first).focus();
}

/**
 * Reactive reduced-motion preference. A local hook (rather than motion's
 * `useReducedMotion`) so the value updates when the media query changes and
 * stays independently testable per mount.
 */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return reduced;
}
