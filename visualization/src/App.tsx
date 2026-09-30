import { useEffect } from "react";
import { MotionConfig } from "motion/react";
import { autoConnect } from "./app/connection";
import { AppShell } from "./components/shell/AppShell";
import { useAppStore } from "./store/appStore";
import {
  applyUiPrefsToDocument,
  useUiPrefsStore,
} from "./store/uiPrefsStore";

export default function App() {
  const theme = useAppStore((s) => s.theme);
  const projectRoot = useAppStore((s) => s.projectRoot);
  const uiPrefs = useUiPrefsStore();

  // Theme is applied at the document root so every token flips together.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  // Local interface preferences (fonts, size, density, motion) are applied
  // to the document as CSS variables/classes; they are client-local.
  useEffect(() => {
    applyUiPrefsToDocument(uiPrefs);
  }, [uiPrefs]);

  useEffect(() => {
    // Connect once on mount (Tauri lease or the stored browser target); when
    // no target is known the connect screen collects address + token.
    void autoConnect(projectRoot);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <MotionConfig reducedMotion={uiPrefs.reducedMotion ? "always" : "user"}>
      <AppShell />
    </MotionConfig>
  );
}
