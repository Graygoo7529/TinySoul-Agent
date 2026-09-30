/**
 * Local interface preferences (implementation plan §20): typography, density
 * and motion. These are client-local — persisted under `tinysoul-ui-prefs`,
 * applied to the document immediately, and never part of the Agent
 * configuration draft. The theme stays in appStore (the shell already
 * consumes it).
 *
 * Only preferences with a real consumer live here: there is no auto-follow,
 * notification or width toggle until a consumer exists.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type SansFontChoice = "inter" | "system" | "serif";
export type MonoFontChoice = "jetbrains" | "system" | "cascadia";
export type DensityChoice = "compact" | "comfortable" | "roomy";

export interface UiPrefs {
  fontSans: SansFontChoice;
  fontMono: MonoFontChoice;
  /** Base font size in px (12–18, default 14). */
  fontSize: number;
  /** Base line height (1.3–1.9, default 1.5). */
  lineHeight: number;
  density: DensityChoice;
  reducedMotion: boolean;
}

export const UI_PREFS_DEFAULTS: UiPrefs = {
  fontSans: "inter",
  fontMono: "jetbrains",
  fontSize: 14,
  lineHeight: 1.5,
  density: "comfortable",
  reducedMotion: false,
};

export const FONT_SIZE_RANGE = { min: 12, max: 18 } as const;
export const LINE_HEIGHT_RANGE = { min: 1.3, max: 1.9 } as const;

export interface UiPrefsState extends UiPrefs {
  setPref: <K extends keyof UiPrefs>(key: K, value: UiPrefs[K]) => void;
  resetDefaults: () => void;
}

function clamp(value: number, range: { min: number; max: number }): number {
  return Math.min(range.max, Math.max(range.min, value));
}

export const useUiPrefsStore = create<UiPrefsState>()(
  persist(
    (set) => ({
      ...UI_PREFS_DEFAULTS,
      setPref: (key, value) =>
        set(() => {
          if (key === "fontSize" && typeof value === "number") {
            return { fontSize: clamp(value, FONT_SIZE_RANGE) };
          }
          if (key === "lineHeight" && typeof value === "number") {
            return { lineHeight: clamp(value, LINE_HEIGHT_RANGE) };
          }
          return { [key]: value };
        }),
      resetDefaults: () => set({ ...UI_PREFS_DEFAULTS }),
    }),
    {
      name: "tinysoul-ui-prefs",
      merge: (persistedState, currentState) => {
        const persisted =
          persistedState !== null && typeof persistedState === "object"
            ? (persistedState as Record<string, unknown>)
            : {};
        return {
          ...currentState,
          fontSans: isSansFont(persisted.fontSans)
            ? persisted.fontSans
            : currentState.fontSans,
          fontMono: isMonoFont(persisted.fontMono)
            ? persisted.fontMono
            : currentState.fontMono,
          fontSize:
            typeof persisted.fontSize === "number"
              ? clamp(persisted.fontSize, FONT_SIZE_RANGE)
              : currentState.fontSize,
          lineHeight:
            typeof persisted.lineHeight === "number"
              ? clamp(persisted.lineHeight, LINE_HEIGHT_RANGE)
              : currentState.lineHeight,
          density: isDensity(persisted.density)
            ? persisted.density
            : currentState.density,
          reducedMotion: persisted.reducedMotion === true,
        };
      },
    },
  ),
);

function isSansFont(value: unknown): value is SansFontChoice {
  return value === "inter" || value === "system" || value === "serif";
}

function isMonoFont(value: unknown): value is MonoFontChoice {
  return value === "jetbrains" || value === "system" || value === "cascadia";
}

function isDensity(value: unknown): value is DensityChoice {
  return value === "compact" || value === "comfortable" || value === "roomy";
}

// ---------------------------------------------------------------------------
// Applying preferences to the document
// ---------------------------------------------------------------------------

const SANS_STACKS: Record<SansFontChoice, string> = {
  inter:
    '"Inter Variable", "Inter", "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  system:
    'system-ui, -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif',
  serif: 'Georgia, "Times New Roman", "Songti SC", "SimSun", serif',
};

const MONO_STACKS: Record<MonoFontChoice, string> = {
  jetbrains:
    '"JetBrains Mono Variable", "JetBrains Mono", "Cascadia Code", Consolas, monospace',
  system: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  cascadia: '"Cascadia Code", ui-monospace, Consolas, monospace',
};

const DENSITY_SCALE: Record<DensityChoice, number> = {
  compact: 0.85,
  comfortable: 1,
  roomy: 1.18,
};

/** Reduced-motion class toggled on the document root; index.css consumes it. */
export const REDUCED_MOTION_CLASS = "ui-reduced-motion";

/**
 * Push the preferences onto the document: CSS custom properties consumed by
 * the trailing section of index.css, plus the reduced-motion class (motion
 * components additionally read MotionConfig in App).
 */
export function applyUiPrefsToDocument(
  prefs: UiPrefs,
  target?: { style: CSSStyleDeclaration; classList: DOMTokenList },
): void {
  const element =
    target ?? (document.documentElement as HTMLElement);
  element.style.setProperty("--font-sans", SANS_STACKS[prefs.fontSans]);
  element.style.setProperty("--font-mono", MONO_STACKS[prefs.fontMono]);
  element.style.setProperty("--ui-font-size", `${prefs.fontSize}px`);
  element.style.setProperty("--ui-line-height", String(prefs.lineHeight));
  element.style.setProperty("--ui-density", String(DENSITY_SCALE[prefs.density]));
  element.classList.toggle(REDUCED_MOTION_CLASS, prefs.reducedMotion);
}
