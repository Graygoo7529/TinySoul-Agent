import { rawText, useI18n } from "../../../i18n";
/** Shared project interface settings, saved independently of Agent configuration. */

import { useEffect, useState, type ReactNode } from "react";

import { SectionCard } from "../../../components/ui/Card";
import { useConnectionStore } from "../../../store/connectionStore";
import {
  FONT_SIZE_RANGE,
  LINE_HEIGHT_RANGE,
  useUiPrefsStore,
  useUiPrefs,
  type LocaleChoice,
  type ThemeMode,
  type DensityChoice,
  type MonoFontChoice,
  type SansFontChoice,
} from "../../../store/uiPrefsStore";
import { SettingsPageBody } from "./controls";
import {
  refreshInterface,
  resetInterfaceDefaults,
  retryInterfaceSave,
  setInterfacePref,
} from "../presentationController";
import { PresentationAssets } from "./PresentationAssets";

const SANS_OPTIONS: { value: SansFontChoice; label: string }[] = [
  { value: "inter", label: "Inter" },
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
  const { t } = useI18n();
  const prefs = useUiPrefs();
  const state = useUiPrefsStore();
  const connected = useConnectionStore((s) => s.phase === "connected" && !s.unreachable);
  const epoch = useConnectionStore((s) => s.epoch);
  useEffect(() => { if (connected) void refreshInterface(); }, [connected, epoch]);
  const disabled = !connected || state.phase !== "ready";

  return (
    <SettingsPageBody>
      <div className="rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 text-[12px] leading-5 text-fg-muted">
        {t("settings.text.29310f302509")}
        <div className="mt-2 flex flex-wrap items-center gap-3" aria-live="polite">
          <span>{!connected ? t("settings.text.d02b78ed97cc")
            : state.phase === "loading" ? t("settings.text.1a0c4ca8917a")
            : state.loadError ? t("settings.text.24446863c2dc")
            : state.saving ? t("settings.text.de70e750bd54")
            : state.saveError ? t("settings.text.6dfc76c8b8cc")
            : state.phase === "ready" ? t("settings.text.bc46e103d1fe") : t("settings.text.1eaed6a80143")}</span>
          <button type="button" className="text-accent disabled:opacity-40" disabled={!connected || state.saving || state.phase === "loading"}
            onClick={() => void refreshInterface(Object.keys(state.pending).length > 0)}>
            {Object.keys(state.pending).length > 0 ? t("settings.text.abf21fc0bb51") : t("settings.text.56e3badc4e6c")}
          </button>
          {state.saveError && <button type="button" className="text-accent disabled:opacity-40" disabled={disabled || state.saving}
            onClick={() => void retryInterfaceSave()}>{t("settings.text.71e1aa94f815")}</button>}
        </div>
        {(state.loadError || state.saveError) && <p className="mt-1 text-danger" role="alert">{state.loadError ?? state.saveError}</p>}
      </div>

      <fieldset disabled={disabled} className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0 disabled:opacity-50">

        <SectionCard title={t("settings.language")} description={t("settings.languageDescription")}>
          <PrefRow label={t("settings.language")}>
            <Segmented
              options={[
                { value: "zh-CN" as LocaleChoice, label: t("settings.locale.zhCN") },
                { value: "en-US" as LocaleChoice, label: t("settings.locale.enUS") },
              ]}
              value={prefs.locale}
              onChange={(next) => setInterfacePref("locale", next)}
            />
          </PrefRow>
        </SectionCard>

        <SectionCard title={t("settings.text.41def7a0febe")} description={t("settings.text.95c25478805a")}>
          <PrefRow label={t("settings.text.a797e30923ac")}>
            <Segmented
              options={THEME_OPTIONS.map((option) => ({
                ...option,
                label: option.value === "light" ? t("settings.theme.light") : t("settings.theme.dark"),
              }))}
              value={prefs.theme}
              onChange={(next) => setInterfacePref("theme", next)}
            />
          </PrefRow>
        </SectionCard>

        <SectionCard
          title={t("settings.text.f4beb9af58f7")}
          description={t("settings.text.f8f238985db4")}
        >
          <PrefRow
            label={t("settings.text.30c49d756643")}
            preview={<FontPreview family="var(--font-sans)" mono={false} />}
          >
            <SelectControl
              options={SANS_OPTIONS.map((option) => ({
                ...option,
                label: t(`settings.font.${option.value}` as "settings.font.inter" | "settings.font.system" | "settings.font.serif"),
              }))}
              value={prefs.fontSans}
              onChange={(next) => setInterfacePref("fontSans", next as SansFontChoice)}
            />
          </PrefRow>
          <PrefRow label={t("settings.text.83ca9e48c37c")} description={`${FONT_SIZE_RANGE.min}–${FONT_SIZE_RANGE.max}px`}>
            <NumberControl
              value={prefs.fontSize}
              min={FONT_SIZE_RANGE.min}
              max={FONT_SIZE_RANGE.max}
              unit="px"
              onChange={(next) => setInterfacePref("fontSize", next)}
            />
          </PrefRow>
          <PrefRow
            label={t("settings.text.65be5133e74b")}
            description={`${LINE_HEIGHT_RANGE.min}–${LINE_HEIGHT_RANGE.max}`}
          >
            <NumberControl
              value={prefs.lineHeight}
              min={LINE_HEIGHT_RANGE.min}
              max={LINE_HEIGHT_RANGE.max}
              step={0.05}
              onChange={(next) => setInterfacePref("lineHeight", next)}
            />
          </PrefRow>
          <PrefRow
            label={t("settings.text.fd3f96571839")}
            preview={<FontPreview family="var(--font-mono)" mono />}
          >
            <SelectControl
              options={MONO_OPTIONS.map((option) => ({
                ...option,
                label: option.value === "jetbrains" ? t("settings.font.jetbrains") : option.value === "system" ? t("settings.font.monoSystem") : t("settings.font.cascadia"),
              }))}
              value={prefs.fontMono}
              onChange={(next) => setInterfacePref("fontMono", next as MonoFontChoice)}
            />
          </PrefRow>
        </SectionCard>

        <SectionCard
          title={t("settings.text.d7da6355bb6b")}
          description={t("settings.text.a306fe6bfa67")}
        >
          <PrefRow label={t("settings.text.f9160c22f517")}>
            <Segmented
              options={DENSITY_OPTIONS.map((option) => ({
                ...option,
                label: t(`settings.density.${option.value}` as "settings.density.compact" | "settings.density.comfortable" | "settings.density.roomy"),
              }))}
              value={prefs.density}
              onChange={(next) => setInterfacePref("density", next)}
            />
          </PrefRow>
          <PrefRow
            label={t("settings.text.25a5aef56243")}
            description={t("settings.text.34634c2542e0")}
          >
            <PreferenceSwitch
              on={prefs.reducedMotion}
              onChange={(next) => setInterfacePref("reducedMotion", next)}
            />
          </PrefRow>
        </SectionCard>

        <div className="flex justify-end">
          <button
            type="button"
            className="h-8 rounded-lg border border-line bg-bg-elev px-3 text-[13px] font-medium text-fg hover:border-line-strong hover:bg-hover"
            onClick={resetInterfaceDefaults}
          >{t("settings.text.05420d7f6eb5")}</button>
        </div>
      </fieldset>
      <PresentationAssets />
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
        <div className="text-[13px] font-medium text-fg">{rawText(label)}</div>
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
          {rawText(option.label)}
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
          {rawText(option.label)}
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
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const parsed = Number(text);
    if (!text.trim() || !Number.isFinite(parsed)) {
      setText(String(value));
      return;
    }
    const next = Math.min(max, Math.max(min, step === 1 ? Math.round(parsed) : parsed));
    setText(String(next));
    if (next !== value) onChange(next);
  };
  return (
    <span className="flex items-center gap-1.5">
      <input
        type="number"
        className="h-8 w-24 rounded-md border border-line bg-bg px-2 text-right text-[12.5px] text-fg outline-none focus:border-accent"
        value={text}
        min={min}
        max={max}
        step={step}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") { setText(String(value)); }
        }}
      />
      {unit !== undefined && (
        <span className="text-[11px] text-fg-faint">{unit}</span>
      )}
    </span>
  );
}

function PreferenceSwitch({
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
