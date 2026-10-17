import { useEffect } from "react";
import { MotionConfig } from "motion/react";
import { autoConnect } from "./app/connection";
import { AppShell } from "./components/shell/AppShell";
import { useAppStore } from "./store/appStore";
import {
  applyUiPrefsToDocument,
  useUiPrefs,
} from "./store/uiPrefsStore";

export default function App() {
  const projectRoot = useAppStore((s) => s.projectRoot);
  const uiPrefs = useUiPrefs();
  const theme = uiPrefs.theme;

  // Theme is applied at the document root so every token flips together.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  // Project interface values and pending edits share the same CSS projection.
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
