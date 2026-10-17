/** Shared project interface values and their unconfirmed local edits. */
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import type { InterfaceSettings } from "../api/v2/presentation";

export type ThemeMode = InterfaceSettings["theme"];
export type SansFontChoice = InterfaceSettings["font_sans"];
export type MonoFontChoice = InterfaceSettings["font_mono"];
export type DensityChoice = InterfaceSettings["density"];

export interface UiPrefs {
  theme: ThemeMode;
  fontSans: SansFontChoice;
  fontMono: MonoFontChoice;
  fontSize: number;
  lineHeight: number;
  density: DensityChoice;
  reducedMotion: boolean;
}

/** Rendering defaults before connecting; never automatically uploaded. */
export const UI_PREFS_DEFAULTS: UiPrefs = {
  theme: "light",
  fontSans: "inter",
  fontMono: "jetbrains",
  fontSize: 14,
  lineHeight: 1.5,
  density: "comfortable",
  reducedMotion: false,
};
export const FONT_SIZE_RANGE = { min: 12, max: 18 } as const;
export const LINE_HEIGHT_RANGE = { min: 1.3, max: 1.9 } as const;

export interface UiPrefsState {
  saved: UiPrefs;
  defaults: UiPrefs;
  pending: Partial<UiPrefs>;
  phase: "idle" | "loading" | "ready" | "error";
  loadError: string | null;
  saving: boolean;
  saveError: string | null;
}

export function initialUiPrefsState(): UiPrefsState {
  return {
    saved: { ...UI_PREFS_DEFAULTS },
    defaults: { ...UI_PREFS_DEFAULTS },
    pending: {},
    phase: "idle",
    loadError: null,
    saving: false,
    saveError: null,
  };
}

export const useUiPrefsStore = create<UiPrefsState>()(initialUiPrefsState);

export function useUiPrefs(): UiPrefs {
  return useUiPrefsStore(useShallow((state) => ({ ...state.saved, ...state.pending })));
}

export function prefsFromApi(values: InterfaceSettings): UiPrefs {
  return {
    theme: values.theme,
    fontSans: values.font_sans,
    fontMono: values.font_mono,
    fontSize: values.font_size,
    lineHeight: values.line_height,
    density: values.density,
    reducedMotion: values.reduced_motion,
  };
}

export function prefsPatchToApi(patch: Partial<UiPrefs>): Partial<InterfaceSettings> {
  return {
    ...(patch.theme !== undefined && { theme: patch.theme }),
    ...(patch.fontSans !== undefined && { font_sans: patch.fontSans }),
    ...(patch.fontMono !== undefined && { font_mono: patch.fontMono }),
    ...(patch.fontSize !== undefined && { font_size: patch.fontSize }),
    ...(patch.lineHeight !== undefined && { line_height: patch.lineHeight }),
    ...(patch.density !== undefined && { density: patch.density }),
    ...(patch.reducedMotion !== undefined && { reduced_motion: patch.reducedMotion }),
  };
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
