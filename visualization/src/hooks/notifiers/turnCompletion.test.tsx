// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "../../store/appStore";
import type { ChatTurn, TurnStatus } from "../../derive/model";
import { useTurnCompletionNotifier } from "./turnCompletion";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  useAppStore.setState({
    toasts: [],
    activeTab: "chat",
    chatPinnedToBottom: true,
    chatScrollRequest: null,
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function Probe({ turns }: { turns: ChatTurn[] }) {
  useTurnCompletionNotifier(turns);
  return null;
}

function turn(status: TurnStatus, turnId = "t1"): ChatTurn {
  return { turnId, status } as ChatTurn;
}

function render(turns: ChatTurn[]) {
  act(() => {
    root.render(<Probe turns={turns} />);
  });
}

const toasts = () => useAppStore.getState().toasts;

describe("useTurnCompletionNotifier", () => {
  it("stays silent while the user is watching the chat", () => {
    render([turn("running")]);
    render([turn("answered")]);
    expect(toasts()).toHaveLength(0);
  });

  it("notifies when the user scrolled away in the chat view", () => {
    useAppStore.setState({ chatPinnedToBottom: false });
    render([turn("running")]);
    render([turn("answered")]);
    expect(toasts()).toHaveLength(1);
    expect(toasts()[0].kind).toBe("success");
    expect(toasts()[0].text).toBe("新回答已完成");
  });

  it("notifies on another tab even though the chat view would be pinned", () => {
    useAppStore.setState({ activeTab: "workspace" });
    render([turn("running")]);
    render([turn("answered")]);
    expect(toasts()).toHaveLength(1);
  });

  it("reports failure as error and exhaustion as info", () => {
    useAppStore.setState({ chatPinnedToBottom: false });
    render([turn("running", "t1")]);
    render([turn("failed", "t1")]);
    render([turn("running", "t2")]);
    render([turn("exhausted", "t2")]);
    expect(toasts().map((t) => t.kind)).toEqual(["error", "info"]);
  });

  it("stays silent for a user-requested stop", () => {
    useAppStore.setState({ chatPinnedToBottom: false });
    render([turn("running")]);
    render([turn("stopped")]);
    expect(toasts()).toHaveLength(0);
  });

  it("ignores turns already finished at mount (restored history)", () => {
    useAppStore.setState({ chatPinnedToBottom: false });
    render([turn("answered")]);
    expect(toasts()).toHaveLength(0);
  });

  it("ignores a different finished turn appearing (no completion flip)", () => {
    useAppStore.setState({ chatPinnedToBottom: false });
    render([turn("answered", "t1")]);
    render([turn("answered", "t2")]);
    expect(toasts()).toHaveLength(0);
  });

  it("its action switches to the chat tab and requests a scroll to the turn", () => {
    useAppStore.setState({ activeTab: "workspace" });
    render([turn("running", "t9")]);
    render([turn("answered", "t9")]);
    const action = toasts()[0]?.action;
    if (!action) throw new Error("expected the toast to carry an action");
    act(() => action.onClick());
    expect(useAppStore.getState().activeTab).toBe("chat");
    expect(useAppStore.getState().chatScrollRequest).toEqual({ turnId: "t9" });
  });
});
