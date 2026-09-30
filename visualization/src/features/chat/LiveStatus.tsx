/**
 * LiveStatus — live activity disclosure for a running turn.
 *
 * Restored from baseline (c479ca0) to work with v2 presentation types.
 *
 * Layout (top to bottom):
 * - Shine-swept headline naming the current activity
 * - Thinking stream (latest reasoning summary, auto-expanded)
 * - Rolling stack of recent semantic steps (phase/domains/skills/actions/...)
 * - Working state zone (todos/milestones)
 *
 * The card breathes a gradient border while the turn runs.
 */

import { useEffect, useState, useRef } from "react";
import { XCircle, Loader2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { ActivityPresentation } from "./presentation";
import { ActivityStep } from "./ActivityStep";
import { useNow } from "../../hooks/useNow";
import { formatDuration } from "../../utils/format";
import { EASE_CALM } from "../../utils/motion";

const ROLL_WINDOW = 14; // Max steps shown
const TRAIL_MAX_PX = 256; // Max height for trail viewport
const FOLD_DELAY_MS = 400; // Delay before fold on settle
const LIVE_FOLD_MS = 300; // Fold animation duration

export interface LiveStatusProps {
  activity: ActivityPresentation;
  mode?: "live" | "settled";
  onStop?: () => void;
}

export function LiveStatus({ activity, mode = "live", onStop }: LiveStatusProps) {
  const live = mode === "live";
  useNow(live, 1000); // Tick every second for timer
  const reduced = useReducedMotion();

  // Settled cards start folded
  const [trailOpen, setTrailOpen] = useState(false);
  const trailOpenedOnce = useRef(false);
  const bodyOpen = live || trailOpen;

  useEffect(() => {
    if (live && !trailOpenedOnce.current) {
      trailOpenedOnce.current = true;
    }
  }, [live]);

  // Elapsed time formatting
  const elapsed = activity.timing.elapsedMs;
  const elapsedSeconds = Math.floor(elapsed / 1000);
  const elapsedFormatted = formatDuration(0, elapsedSeconds);

  // Trail (most recent steps)
  const trail = activity.trail.slice(-ROLL_WINDOW);

  return (
    <div className="relative overflow-hidden rounded-lg border bg-bg-elev">
      {/* Breathing border gradient (live only) */}
      {live && !reduced && (
        <div className="pointer-events-none absolute inset-0 rounded-lg border border-accent/30">
          <div className="absolute inset-0 animate-shine bg-gradient-to-r from-transparent via-accent/20 to-transparent" />
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {live && (
            <Loader2 size={14} className="shrink-0 animate-spin text-accent" />
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="truncate text-[13px] font-medium text-fg">
                {activity.headline.label}
              </span>
              {activity.headline.domain && (
                <span className="shrink-0 font-mono text-[11px] text-fg-faint">
                  {activity.headline.domain}
                </span>
              )}
            </div>
            {activity.headline.skill && (
              <div className="mt-0.5 text-[11px] text-fg-muted">
                with {activity.headline.skill}
              </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <span className="font-mono text-[11px] text-fg-faint">{elapsedFormatted}</span>
          {live && activity.canStop && onStop && (
            <button
              onClick={onStop}
              title="Stop turn"
              className="inline-flex h-6 items-center gap-1 rounded-md bg-danger/10 px-2 text-[11px] text-danger transition-colors hover:bg-danger/20"
            >
              <XCircle size={12} />
              Stop
            </button>
          )}
          {!live && (
            <button
              onClick={() => setTrailOpen(!trailOpen)}
              className="text-[11px] text-accent transition-colors hover:text-accent/80"
            >
              {trailOpen ? "Collapse" : "Expand"}
            </button>
          )}
        </div>
      </div>

      {/* Body (thinking + trail + working) */}
      <AnimatePresence initial={false}>
        {bodyOpen && (
          <motion.div
            initial={reduced ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduced ? false : { height: 0, opacity: 0 }}
            transition={{ duration: LIVE_FOLD_MS / 1000, ease: EASE_CALM, delay: live ? 0 : FOLD_DELAY_MS / 1000 }}
            className="overflow-hidden border-t border-line"
          >
            <div className="px-4 pb-4">
              {/* Thinking */}
              {activity.thinking.current && (
                <div className="mt-3 rounded-lg bg-accent-soft/30 px-3 py-2">
                  <div className="text-[12px] italic leading-relaxed text-fg-muted">
                    {activity.thinking.current}
                  </div>
                </div>
              )}

              {/* Trail (rolling activity steps) */}
              {trail.length > 0 && (
                <div
                  className="mt-3 space-y-2"
                  style={{ maxHeight: live ? `${TRAIL_MAX_PX}px` : undefined }}
                >
                  <AnimatePresence initial={false} mode="popLayout">
                    {trail.map((step) => (
                      <motion.div
                        key={step.id}
                        initial={reduced || !live ? false : { opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={reduced || !live ? false : { opacity: 0, scale: 0.95 }}
                        transition={{ duration: 0.3, ease: EASE_CALM }}
                        layout={!reduced && live}
                      >
                        <ActivityStep item={step} animate={live} />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              )}

              {/* Working (todos/milestones) */}
              {(activity.working.todos.length > 0 || activity.working.milestones.length > 0) && (
                <div className="mt-4 space-y-2">
                  {activity.working.milestones.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10.5px] font-medium uppercase tracking-wide text-fg-faint">
                        Milestones
                      </div>
                      {activity.working.milestones.map((milestone) => (
                        <div key={milestone.id} className="flex items-start gap-2 text-[12px]">
                          <span
                            className={
                              milestone.status === "done"
                                ? "text-success"
                                : milestone.status === "blocked"
                                  ? "text-warning"
                                  : "text-fg-faint"
                            }
                          >
                            {milestone.status === "done" ? "✓" : milestone.status === "blocked" ? "⊘" : "−"}
                          </span>
                          <span className="text-fg">{milestone.text}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {activity.working.todos.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10.5px] font-medium uppercase tracking-wide text-fg-faint">
                        Todos
                      </div>
                      {activity.working.todos.map((todo) => (
                        <div key={todo.id} className="flex items-start gap-2 text-[12px]">
                          <span className={todo.status === "done" ? "text-success" : "text-fg-faint"}>
                            {todo.status === "done" ? "✓" : "○"}
                          </span>
                          <span className="text-fg-muted">{todo.text}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Incomplete warning */}
              {activity.incomplete && (
                <div className="mt-3 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2">
                  <div className="text-[11px] text-warning">
                    Activity stream incomplete (connection lost or gap detected)
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
