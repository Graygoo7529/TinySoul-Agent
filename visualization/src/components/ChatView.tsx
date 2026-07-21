import { useEffect, useRef, useState } from "react";
import { Send, Square } from "lucide-react";

import { randomId } from "../utils/randomId";

import { useAppStore } from "../store/appStore";
import { useDerivedChat } from "../hooks/useDerivedChat";
import { MessageBubble } from "./MessageBubble";

export function ChatView() {
  const { events, client, status } = useAppStore();
  const turns = useDerivedChat(events);
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isTurnActive = status?.turn_active ?? false;

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [text]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, events.length]);

  const send = async () => {
    if (!client || !text.trim()) return;
    try {
      const commandId = randomId();
      await client.submitInput({
        text: text.trim(),
        command_id: commandId,
        metadata: { client_message_id: commandId },
      });
      setText("");
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const stop = async () => {
    if (!client) return;
    try {
      await client.submitControl({ kind: "stop_turn", command_id: randomId() });
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
    <div className="chat-view">
      <div className="chat-messages">
        {turns.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon">
              <span style={{ fontSize: 48 }}>💬</span>
            </div>
            <h3 style={{ margin: "0 0 8px", color: "var(--text)" }}>
              Start a conversation
            </h3>
            <p className="text-sm">
              Send a message to begin a new turn with TinySoul.
            </p>
          </div>
        )}
        {turns.map((turn) => (
          <MessageBubble key={turn.turnId} turn={turn} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="composer">
        <div className="composer-inner">
          <textarea
            ref={textareaRef}
            placeholder="Message TinySoul…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={!client}
          />
          <div className="composer-actions">
            {isTurnActive ? (
              <button
                className="send-btn"
                onClick={() => void stop()}
                title="Stop turn"
              >
                <Square size={14} />
              </button>
            ) : (
              <button
                className="send-btn"
                onClick={() => void send()}
                disabled={!client || !text.trim()}
                title="Send"
              >
                <Send size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
