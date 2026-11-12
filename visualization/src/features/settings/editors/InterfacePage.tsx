import { useI18n, message, resolveText, effectiveLocale, type UiText } from "../../../i18n";
/** Shared project interface settings, saved independently of Agent configuration. */

import { useEffect, useState, type ReactNode } from "react";

import { SectionCard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { isTauri } from "@tauri-apps/api/core";
import {
  chooseDataDir,
  listLocal,
  localStoreState,
  openDataDir,
  subscribeLocalStore,
  type LocalStoreState,
} from "../../../app/localStore/localStore";
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
import { SettingsPageBody } from "./draftCompositeControls";
import { inputChrome } from "../fieldChrome";
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
        {t("settings.savedInThisProjectThisInterfaceUpdatesImmediatelyOther")}
        <div className="mt-2 flex flex-wrap items-center gap-3" aria-live="polite">
          <span>{!connected ? t("settings.connectToEditSharedInterfaceSettings")
            : state.phase === "loading" ? t("settings.loadingInterfaceSettings")
            : state.loadError ? t("settings.interfaceSettingsCouldNotBeLoaded")
            : state.saving ? t("settings.savingInterfaceSettings")
            : state.saveError ? t("settings.interfaceSettingsCouldNotBeSaved")
            : state.phase === "ready" ? t("settings.savedToProject") : t("settings.waitingForInterfaceSettings")}</span>
          <button type="button" className="text-accent disabled:opacity-40" disabled={!connected || state.saving || state.phase === "loading"}
            onClick={() => void refreshInterface(Object.keys(state.pending).length > 0)}>
            {Object.keys(state.pending).length > 0 ? t("settings.discardChangesAndReload") : t("settings.refresh")}
          </button>
          {state.saveError && <button type="button" className="text-accent disabled:opacity-40" disabled={disabled || state.saving}
            onClick={() => void retryInterfaceSave()}>{t("settings.retrySaving")}</button>}
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

        <SectionCard title={t("settings.appearance")} description={t("settings.themeOfTheWholeInterface")}>
          <PrefRow label={t("settings.theme")}>
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
          title={t("settings.typography")}
          description={t("settings.readingFontsSizeAndLineHeightAcrossTheApp")}
        >
          <PrefRow
            label={t("settings.interfaceFont")}
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
          <PrefRow label={t("settings.fontSize")} description={`${FONT_SIZE_RANGE.min}–${FONT_SIZE_RANGE.max}px`}>
            <NumberControl
              value={prefs.fontSize}
              min={FONT_SIZE_RANGE.min}
              max={FONT_SIZE_RANGE.max}
              unit="px"
              onChange={(next) => setInterfacePref("fontSize", next)}
            />
          </PrefRow>
          <PrefRow
            label={t("settings.lineHeight")}
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
            label={t("settings.codeFont")}
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
          title={t("settings.layoutMotion")}
          description={t("settings.spacingDensityAndAnimationBehavior")}
        >
          <PrefRow label={t("settings.density")}>
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
            label={t("settings.reduceMotion")}
            description={t("settings.minimizesAnimationsAndTransitionsAcrossTheInterface")}
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
          >{t("settings.resetProjectInterfaceDefaults")}</button>
        </div>
      </fieldset>

      <LocalDataSection />

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
        className={`${inputChrome} w-24 text-right`}
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
      className={`relative h-5.5 w-10 shrink-0 rounded-full transition-colors focus-ring ${
        on ? "bg-accent" : "bg-line-strong"
      }`}
    >
      <span
        className={`absolute left-0 top-0.5 h-4.5 w-4.5 rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Local data directory
// ---------------------------------------------------------------------------

/** Local data directory section: where this device's frontend data lives
 *  (connection profile, UI state), with open/change affordances. The browser
 *  case is labeled honestly as browser storage. */
function LocalDataSection() {
  const { t } = useI18n();
  const [store, setStore] = useState<LocalStoreState>(() => localStoreState());
  const [keys, setKeys] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<UiText | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () =>
      subscribeLocalStore(() => {
        setStore(localStoreState());
        void listLocal().then(setKeys);
      }),
    [],
  );
  useEffect(() => {
    void listLocal().then(setKeys);
  }, [store]);

  const choose = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const result = await chooseDataDir();
      if (result.kind === "loaded") {
        window.location.reload();
        return;
      }
      if (result.kind === "copied") {
        setNote(message("settings.localDataCopied", { count: result.keys }));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard
      title={t("settings.localData")}
      description={t("settings.localDataDescription")}
      actions={
        store.mode === "tauri" ? (
          <Badge tone="green">{t("settings.localDataEnabled")}</Badge>
        ) : (
          <Badge tone="yellow">{t("settings.localDataBrowserMode")}</Badge>
        )
      }
    >
      <div className="space-y-2 text-[12.5px]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-fg">{t("settings.localDataCurrentDir")}</div>
            <div className="mt-0.5 text-[11px] text-fg-faint">
              {store.mode === "tauri" ? t("settings.localDataAtomic") : t("settings.localDataBrowserHint")}
            </div>
          </div>
          <div className="max-w-full truncate font-mono text-[11.5px] text-fg-muted">
            {store.dir ?? t("settings.localDataBrowserMode")}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-fg">{t("settings.localDataSaved")}</div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-fg-faint">{t("settings.localDataItemsCount", { count: keys.length })}</span>
            {isTauri() && store.mode === "tauri" && (
              <Button variant="ghost" size="xs" onClick={() => void openDataDir()}>
                {t("settings.localDataOpen")}
              </Button>
            )}
            {isTauri() && (
              <Button variant="ghost" size="xs" loading={busy} onClick={() => void choose()}>
                {store.mode === "tauri" ? t("settings.localDataChange") : t("settings.localDataChoose")}
              </Button>
            )}
          </div>
        </div>
        {!isTauri() && (
          <div className="text-[11px] text-fg-faint">{t("settings.localDataDesktopHint")}</div>
        )}
        {isTauri() && (
          <div className="text-[11px] text-fg-faint">{t("settings.localDataChooseHint")}</div>
        )}
        {note !== null && <div className="text-[11px] text-success">{resolveText(note, effectiveLocale())}</div>}
        {error !== null && (
          <div className="text-[11px] text-danger">{t("settings.localDataChooseFailed", { detail: error })}</div>
        )}
      </div>
    </SectionCard>
  );
}
