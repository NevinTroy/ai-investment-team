"use client";

import type { ChatSummary } from "@/lib/types";
import { fmtDate } from "@/lib/gcal";

export default function Sidebar({
  chats,
  activeChatId,
  onSelect,
  onNewChat,
}: {
  chats: ChatSummary[];
  activeChatId: string | null;
  onSelect: (chatId: string) => void;
  onNewChat: () => void;
}) {
  return (
    <div id="sidebar">
      <div className="sidebar-header">
        <button className="sidebar-new-btn" onClick={onNewChat}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New chat
        </button>
      </div>
      <div className="sidebar-label">History</div>
      <div id="chat-list">
        {chats.length === 0 ? (
          <div className="chat-list-empty">No chats yet</div>
        ) : (
          chats.map((row) => (
            <div
              key={row.id}
              className={`chat-list-item${row.id === activeChatId ? " active" : ""}`}
              onClick={() => onSelect(row.id)}
            >
              <div className="chat-list-title">{row.title || row.company || row.question || "Untitled"}</div>
              <div className="chat-list-meta">
                <span className={`chat-list-status status-${row.status}`}>{row.status}</span>
                <span>{fmtDate(row.created_at)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
