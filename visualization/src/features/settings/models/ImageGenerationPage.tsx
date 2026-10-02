import { settingsText } from "../i18n";
/**
 * Image Generation settings page (plan §16.7): an honest reservation. The
 * backend has no image-generation configuration surface yet, so this page
 * explains the intended shape instead of rendering fake controls.
 */

import { ImageIcon } from "lucide-react";

export function ImageGenerationPage() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-line bg-bg-elev p-6 text-center shadow-card">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-hover text-fg-muted">
          <ImageIcon size={20} />
        </div>
        <h2 className="text-sm font-semibold text-fg">暂不可配置</h2>
        <p className="mt-2 text-[12px] leading-5 text-fg-muted">{settingsText("TinySoul has no image-generation capability today. When it arrives it will follow the same model as this group: reusable providers, logical models with ordered bindings, and named uses selected by the features that need them.")}</p>
        <p className="mt-2 text-[11px] leading-4 text-fg-faint">{settingsText("There is nothing to save or test here — this page intentionally has no controls.")}</p>
      </div>
    </div>
  );
}
