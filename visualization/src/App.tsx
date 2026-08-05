import { useEffect } from "react";
import { useAppStore } from "./store/appStore";
import { useBackend } from "./hooks/useBackend";
import { AppShell } from "./components/shell/AppShell";

export default function App() {
  const { connect } = useBackend();
  const projectRoot = useAppStore((s) => s.projectRoot);
  const theme = useAppStore((s) => s.theme);

  // Theme is applied at the document root so every token flips together.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    void connect(projectRoot);
    // Connect once on mount; retries are driven by the disconnected screen
    // and the initializing poller inside useBackend.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <AppShell connect={connect} />;
}
