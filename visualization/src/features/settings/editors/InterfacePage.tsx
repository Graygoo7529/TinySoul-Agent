/**
 * Interface settings (implementation plan §20): local reading-experience
 * preferences — theme, typography, density, reduced motion. They apply to
 * this client immediately, persist locally, and never touch the Agent
 * configuration. Preferences without a real consumer (auto-follow,
 * notifications, panel widths) are intentionally absent.
 */

import type { ReactNode } from "react";

import { SectionCard } from "../../../components/ui/Card";
import { useAppStore, type ThemeMode } from "../../../store/appStore";
import {
  FONT_SIZE_RANGE,
  LINE_HEIGHT_RANGE,
  useUiPrefsStore,
  type DensityChoice,
  type MonoFontChoice,
  type SansFontChoice,
} from "../../../store/uiPrefsStore";
import { SettingsPageBody } from "./controls";

const SANS_OPTIONS: { value: SansFontChoice; label: string }[] = [
  { value: "inter", label: "Inter (default)" },
  { value: "system", label: "System" },
  { value: "serif", label: "Serif" },
];

const MONO_OPTIONS: { value: MonoFontChoice; label: string }[] = [
  { value: "jetbrains", label: "JetBrains Mono (default)" },
  { value: "system", label: "System mono" },
  { value: "cascadia", label: "Cascadia Code" },
];

const DENSITY_OPTIONS: { value: DensityChoice; label: string }[] = [
  { value: "compact", label: "Compact" },
  { value: "comfortable", label: "Comfortable" },
  { value: "roomy", label: "Roomy" },
];

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function InterfacePage() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const prefs = useUiPrefsStore();
  const resetDefaults = useUiPrefsStore((s) => s.resetDefaults);

  const resetAll = () => {
    resetDefaults();
    setTheme("light");
  };

  return (
    <SettingsPageBody>
      <div className="rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 text-[12px] leading-5 text-fg-muted">
        These preferences apply to this client immediately and are stored
        locally. They never change the Agent&apos;s configuration or other
        clients.
      </div>

      <SectionCard title="Appearance" description="Theme of the whole interface.">
        <PrefRow label="Theme">
          <Segmented
            options={THEME_OPTIONS}
            value={theme}
            onChange={(next) => setTheme(next)}
          />
        </PrefRow>
      </SectionCard>

      <SectionCard
        title="Typography"
        description="Reading fonts, size and line height across the app."
      >
        <PrefRow
          label="Interface font"
          preview={<FontPreview family="var(--font-sans)" mono={false} />}
        >
          <SelectControl
            options={SANS_OPTIONS}
            value={prefs.fontSans}
            onChange={(next) => prefs.setPref("fontSans", next as SansFontChoice)}
          />
        </PrefRow>
        <PrefRow label="Font size" description={`${FONT_SIZE_RANGE.min}–${FONT_SIZE_RANGE.max}px`}>
          <NumberControl
            value={prefs.fontSize}
            min={FONT_SIZE_RANGE.min}
            max={FONT_SIZE_RANGE.max}
            unit="px"
            onChange={(next) => prefs.setPref("fontSize", next)}
          />
        </PrefRow>
        <PrefRow
          label="Line height"
          description={`${LINE_HEIGHT_RANGE.min}–${LINE_HEIGHT_RANGE.max}`}
        >
          <NumberControl
            value={prefs.lineHeight}
            min={LINE_HEIGHT_RANGE.min}
            max={LINE_HEIGHT_RANGE.max}
            step={0.05}
            onChange={(next) => prefs.setPref("lineHeight", next)}
          />
        </PrefRow>
        <PrefRow
          label="Code font"
          preview={<FontPreview family="var(--font-mono)" mono />}
        >
          <SelectControl
            options={MONO_OPTIONS}
            value={prefs.fontMono}
            onChange={(next) => prefs.setPref("fontMono", next as MonoFontChoice)}
          />
        </PrefRow>
      </SectionCard>

      <SectionCard
        title="Layout & Motion"
        description="Spacing density and animation behavior."
      >
        <PrefRow label="Density">
          <Segmented
            options={DENSITY_OPTIONS}
            value={prefs.density}
            onChange={(next) => prefs.setPref("density", next)}
          />
        </PrefRow>
        <PrefRow
          label="Reduce motion"
          description="Minimizes animations and transitions across the interface."
        >
          <LocalSwitch
            on={prefs.reducedMotion}
            onChange={(next) => prefs.setPref("reducedMotion", next)}
          />
        </PrefRow>
      </SectionCard>

      <div className="flex justify-end">
        <button
          type="button"
          className="h-8 rounded-lg border border-line bg-bg-elev px-3 text-[13px] font-medium text-fg hover:border-line-strong hover:bg-hover"
          onClick={resetAll}
        >
          Reset interface defaults
        </button>
      </div>
    </SettingsPageBody>
  );
}

function PrefRow({
  label,
  description,
  preview,
  children,
}: {
  label: string;
  description?: string;
  preview?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-fg">{label}</div>
        {description !== undefined && (
          <div className="mt-0.5 text-[11px] text-fg-muted">{description}</div>
        )}
        {preview}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function FontPreview({ family, mono }: { family: string; mono: boolean }) {
  return (
    <div
      className="mt-1 rounded-md bg-bg-sunken px-2 py-1 text-[13px] text-fg-muted"
      style={{ fontFamily: family }}
    >
      {mono ? "const answer = await agent.think()" : "The quick brown fox, 敏捷的棕色狐狸 123"}
    </div>
  );
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <span className="inline-flex overflow-hidden rounded-lg border border-line">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`h-8 px-3 text-[12px] font-medium transition-colors ${
            option.value === value
              ? "bg-accent-soft text-accent"
              : "bg-bg-elev text-fg-muted hover:bg-hover hover:text-fg"
          }`}
        >
          {option.label}
        </button>
      ))}
    </span>
  );
}

function SelectControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <select
      className="h-8 w-52 rounded-md border border-line bg-bg px-2 text-[12.5px] text-fg outline-none focus:border-accent"
      value={value}
      onChange={(event) => onChange(event.target.value as T)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function NumberControl({
  value,
  min,
  max,
  step = 1,
  unit,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (next: number) => void;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <input
        type="number"
        className="h-8 w-24 rounded-md border border-line bg-bg px-2 text-right text-[12.5px] text-fg outline-none focus:border-accent"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) onChange(next);
        }}
      />
      {unit !== undefined && (
        <span className="text-[11px] text-fg-faint">{unit}</span>
      )}
    </span>
  );
}

function LocalSwitch({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={`relative w-10 shrink-0 rounded-full transition-colors ${
        on ? "bg-accent" : "bg-line-strong"
      }`}
      style={{ height: 22 }}
    >
      <span
        className={`absolute top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-[19px]" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}
