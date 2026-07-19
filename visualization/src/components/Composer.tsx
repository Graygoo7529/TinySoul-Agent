import { useState, useRef, useEffect } from "react";
import { Send, Square } from "lucide-react";

import { useAppStore } from "../store/appStore";

export function Composer() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { client, status } = useAppStore();
  const isTurnActive = status?.turn_active ?? false;

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [text]);

  const send = async () => {
    if (!client || !text.trim()) return;
    try {
      await client.submitInput({ text: text.trim(), metadata: { client_message_id: crypto.randomUUID() } });
      setText("");
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const stop = async () => {
    if (!client) return;
    try {
      await client.submitControl({ kind: "stop_turn" });
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="composer">
      <textarea
        ref={textareaRef}
        className="textarea"
        placeholder="Message TinySoul…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        disabled={!client}
      />
      {isTurnActive ? (
        <button className="btn btn-danger" onClick={stop} disabled={!client}>
          <Square size={16} />
          Stop
        </button>
      ) : (
        <button className="btn btn-primary" onClick={() => void send()} disabled={!client || !text.trim()}>
          <Send size={16} />
          Send
        </button>
      )}
    </div>
  );
}
