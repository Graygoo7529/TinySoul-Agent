import { useEffect } from "react";
import { autoConnect } from "./app/connection";
import { AppShell } from "./components/shell/AppShell";
import { useAppStore } from "./store/appStore";

export default function App() {
  const theme = useAppStore((s) => s.theme);
  const projectRoot = useAppStore((s) => s.projectRoot);

  // Theme is applied at the document root so every token flips together.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    // Connect once on mount (Tauri lease or the stored browser target); when
    // no target is known the connect screen collects address + token.
    void autoConnect(projectRoot);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <AppShell />;
}
