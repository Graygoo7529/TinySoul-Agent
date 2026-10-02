import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";

// Geometry and timing from c479ca0 ChatView. Only the input projection changed.
const TOP_ANCHOR = 20;
const ANCHOR_GLIDE_MS = 700;
const BOTTOM_GAP = 32;

export function useConversationScroll(latestId: string | null, running: boolean, recovering: boolean) {
  const reduced = useReducedMotion();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const current = useRef({ running, latestId });
  current.current = { running, latestId };
  const programmatic = useRef<number | null>(null);
  const glideFrame = useRef<number | undefined>(undefined);
  const following = useRef(true);
  const [pinned, setPinned] = useState(true);
  const setFollowing = (value: boolean) => { following.current = value; setPinned(value); };
  const lastTurn = () => {
    const list = contentRef.current?.querySelectorAll<HTMLElement>("[data-turn-root]");
    return list?.[list.length - 1] ?? null;
  };
  const spacer = () => contentRef.current?.querySelector<HTMLElement>("[data-chat-spacer]") ?? null;
  const updateSpacer = () => {
    const scroll = scrollRef.current;
    const tail = spacer();
    const turn = lastTurn();
    if (!scroll || !tail || !turn) return;
    const gap = turn.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    const anchor = scroll.scrollTop + gap - TOP_ANCHOR;
    const base = scroll.scrollHeight - tail.offsetHeight;
    tail.style.height = `${Math.max(BOTTOM_GAP, anchor + scroll.clientHeight - base)}px`;
  };
  const anchorTarget = () => {
    const scroll = scrollRef.current;
    const turn = lastTurn();
    if (!scroll || !turn) return 0;
    const gap = turn.getBoundingClientRect().top - scroll.getBoundingClientRect().top;
    return Math.max(0, Math.min(scroll.scrollTop + gap - TOP_ANCHOR, scroll.scrollHeight - scroll.clientHeight));
  };
  const followTarget = (): number | null => {
    const scroll = scrollRef.current;
    const turn = lastTurn();
    if (!scroll || !turn) return null;
    const streaming = turn.querySelector(".answer-streaming") !== null;
    if (!current.current.running && !streaming) return null;
    if (streaming && turn.offsetHeight + TOP_ANCHOR + 24 > scroll.clientHeight) {
      return Math.max(0, scroll.scrollHeight - scroll.clientHeight - (spacer()?.offsetHeight ?? 0));
    }
    return anchorTarget();
  };
  const cancelGlide = () => {
    if (glideFrame.current !== undefined) cancelAnimationFrame(glideFrame.current);
    glideFrame.current = undefined;
  };
  const glideTo = (target: number) => {
    const scroll = scrollRef.current;
    if (!scroll) return;
    cancelGlide();
    if (reduced) { programmatic.current = target; scroll.scrollTop = target; return; }
    const start = scroll.scrollTop;
    const t0 = performance.now();
    const step = (time: number) => {
      const fraction = Math.min(1, (time - t0) / ANCHOR_GLIDE_MS);
      programmatic.current = target;
      scroll.scrollTop = start + (target - start) * (1 - Math.pow(1 - fraction, 4));
      glideFrame.current = fraction < 1 ? requestAnimationFrame(step) : undefined;
    };
    glideFrame.current = requestAnimationFrame(step);
  };
  useEffect(() => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return;
    const onResize = () => {
      updateSpacer();
      if (!following.current || glideFrame.current !== undefined) return;
      const target = followTarget();
      if (target === null || Math.abs(scroll.scrollTop - target) < 1) return;
      programmatic.current = target;
      scroll.scrollTop = target;
    };
    onResize();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(onResize);
    observer.observe(scroll);
    observer.observe(content);
    return () => observer.disconnect();
    // Callbacks read current projection from refs and measured DOM geometry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestId === null, recovering]);

  const landed = useRef(false);
  const previous = useRef(latestId);
  useEffect(() => {
    if (recovering || latestId === null) return;
    const scroll = scrollRef.current;
    if (!scroll) return;
    updateSpacer();
    if (!landed.current) {
      landed.current = true;
      previous.current = latestId;
      setFollowing(true);
      const target = running ? anchorTarget() : Math.max(0, scroll.scrollHeight - scroll.clientHeight);
      programmatic.current = target;
      scroll.scrollTop = target;
    } else if (previous.current !== latestId) {
      previous.current = latestId;
      setFollowing(true);
      glideTo(anchorTarget());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestId, recovering]);
  useEffect(() => () => cancelGlide(), []);

  return {
    scrollRef, contentRef, pinned,
    jumpToLatest: () => { setFollowing(true); updateSpacer(); glideTo(followTarget() ?? anchorTarget()); },
    onScroll: () => {
      const scroll = scrollRef.current;
      if (!scroll) return;
      if (programmatic.current !== null) {
        if (Math.abs(scroll.scrollTop - programmatic.current) < 2) programmatic.current = null;
        return;
      }
      const target = followTarget();
      setFollowing(target === null
        ? scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 120
        : Math.abs(scroll.scrollTop - target) < 120);
    },
    onWheel: (event: React.WheelEvent) => {
      cancelGlide(); programmatic.current = null;
      if (event.deltaY < 0) setFollowing(false);
    },
    onTouchStart: () => { cancelGlide(); programmatic.current = null; setFollowing(false); },
  };
}
