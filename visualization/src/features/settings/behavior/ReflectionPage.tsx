import { t } from "../../../i18n";
/**
 * Reflection Schedule settings page (config-coverage §3.5): the daily
 * reflection switch, its local wall-clock time, the business timezone and the
 * archive root. Starting one reflection immediately belongs to the Home and
 * Memory pages (where the review scope is visible), so this page has no
 * trigger button.
 */

import { useEffect, useState } from "react";

import { SectionCard } from "../../../components/ui/Card";
import {
  FieldSection,
  SettingsPageBody,
  type DraftFieldApi,
} from "../editors/controls";

export function ReflectionPage() {
  return (
    <SettingsPageBody>
      <SectionCard
        title={t("settings.text.dd93a5c7b77e")}
        description={t("settings.text.ccf610176e56")}
      >
        <div className="px-4 py-3 text-[12px] leading-5 text-fg-muted">{t("settings.text.01758597f026")}</div>
      </SectionCard>
      <FieldSection
        title={t("settings.text.81b507f7c2b9")}
        description={t("settings.text.15fe4e96ea47")}
        paths={[
          "reflection.schedule.enabled",
          "reflection.schedule.daily_time",
          "reflection.timezone",
          "reflection.archive_root",
        ]}
        overrides={{
          "reflection.schedule.daily_time": {
            render: (api) => <DailyTimeControl api={api} />,
          },
        }}
      />
    </SettingsPageBody>
  );
}

/**
 * Local wall-clock editor (HH:MM). Clearing the input withdraws the override
 * and restores the owner default (00:15); invalid text never reaches the
 * draft.
 */
function DailyTimeControl({ api }: { api: DraftFieldApi }) {
  const display = typeof api.value === "string" ? api.value : "";
  const [text, setText] = useState(display);
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    setText(display);
    setInvalid(false);
  }, [display]);

  const commit = () => {
    if (text === display) return;
    if (text === "") {
      setInvalid(false);
      api.clear();
      return;
    }
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(text)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    api.set(text);
  };

  return (
    <span className="flex items-center gap-1.5">
      <input
        type="time"
        aria-label={api.path}
        className={`h-8 rounded-md border bg-bg px-2 font-mono text-[12.5px] text-fg outline-none transition-colors focus:border-accent disabled:opacity-50 ${invalid ? "border-danger" : "border-line"}`}
        value={text}
        disabled={api.readOnly !== null}
        onChange={(event) => {
          setText(event.target.value);
          setInvalid(false);
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
          if (event.key === "Escape") {
            setText(display);
            setInvalid(false);
          }
        }}
      />
      {invalid && (
        <span className="text-[11px] whitespace-nowrap text-danger">{t("settings.text.4af7e0177b20")}</span>
      )}
    </span>
  );
}
