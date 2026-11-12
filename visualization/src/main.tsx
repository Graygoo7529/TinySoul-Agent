import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initLocalStore } from "./app/localStore/localStore";
import { useAppStore } from "./store/appStore";
import "./styles/index.css";

// Hydrate the local store (data dir on desktop, browser storage elsewhere),
// then rehydrate persisted UI state from wherever it now lives.
void initLocalStore().then(() => {
  void useAppStore.persist.rehydrate();
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
