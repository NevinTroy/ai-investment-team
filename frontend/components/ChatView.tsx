"use client";

import { useEffect, useRef } from "react";
import Avatar from "./Avatar";
import AgentsCard from "./AgentsCard";
import PdfSection from "./PdfSection";
import FollowupCard from "./FollowupCard";
import NetworkPanel from "./NetworkPanel";
import type { AppState } from "@/app/page";

export default function ChatView({
  state,
  onToggleAgent,
  onNewChat,
}: {
  state: AppState;
  onToggleAgent: (id: string) => void;
  onNewChat: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.phase, state.agents, state.memoData, state.neighbors]);

  const showAgents =
    (state.phase === "running" || state.phase === "done") &&
    !state.rejectedReason &&
    Object.keys(state.agents).length + (state.phase === "running" ? 1 : 0) > 0;

  const deployText = state.company ? (
    <>
      On it — deploying a research crew to evaluate <b>{state.company}</b> as an investment.
      Here&apos;s the live status.
    </>
  ) : (
    <>On it — deploying the research crew. Here&apos;s the live status.</>
  );

  const showWatchlistCard =
    state.phase === "done" &&
    !state.fromHistory &&
    (state.memoData?.recommendation || "").toLowerCase() === "watchlist";

  return (
    <div id="chat" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div id="chat-scroll" ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "28px 24px 24px" }}>
        <div id="chat-body" style={{ maxWidth: 760, margin: "0 auto", display: "flex", flexDirection: "column", gap: 22 }}>
          <div className="user-row">
            <div className="user-bubble">{state.query}</div>
          </div>

          {state.phase === "checking" && (
            <div className="asst-row">
              <Avatar />
              <div className="asst-body">
                <div className="asst-text" style={{ color: "#7c7c82", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ display: "inline-flex", gap: 4 }}>
                    {[0, 0.2, 0.4].map((delay) => (
                      <span
                        key={delay}
                        style={{
                          width: 5,
                          height: 5,
                          borderRadius: "50%",
                          background: "#57575c",
                          animation: `pulseDot 1.2s ease-in-out ${delay}s infinite`,
                        }}
                      />
                    ))}
                  </span>
                  Reviewing your question…
                </div>
              </div>
            </div>
          )}

          {showAgents && (
            <div className="asst-row">
              <Avatar />
              <div className="asst-body">
                <div className="asst-text">{deployText}</div>
                <AgentsCard
                  agents={state.agents}
                  selectedAgents={state.selectedAgents}
                  expanded={state.expanded}
                  onToggle={onToggleAgent}
                />
              </div>
            </div>
          )}

          {state.rejectedReason && (
            <div className="asst-row">
              <Avatar />
              <div className="asst-body">
                <div className="asst-text">
                  I can only help with investment decisions on specific companies.{" "}
                  {state.rejectedReason}
                  <br />
                  <br />
                  Try asking something like <i>&quot;Should we invest in Stripe?&quot;</i>
                </div>
              </div>
            </div>
          )}

          {state.errorMessage && (
            <div className="asst-row">
              <Avatar />
              <div className="asst-body">
                <div className="asst-text" style={{ color: "#e07070" }}>Error: {state.errorMessage}</div>
              </div>
            </div>
          )}

          {state.phase === "done" && state.memoData && !state.rejectedReason && (
            <PdfSection memo={state.memoData} company={state.company} />
          )}

          {showWatchlistCard && (
            <FollowupCard chatId={state.chatId} company={state.company} question={state.query} />
          )}

          {state.phase === "done" && !state.rejectedReason && !state.errorMessage && (
            <NetworkPanel neighbors={state.neighbors} newPos={state.newPos} company={state.company} />
          )}
        </div>
      </div>

      <div id="composer">
        <div className="composer-inner">
          <span className="composer-placeholder">
            {state.company ? `Ask a follow-up about ${state.company}…` : "Ask a follow-up…"}
          </span>
          <button className="new-chat-btn" onClick={onNewChat}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New chat
          </button>
        </div>
      </div>
    </div>
  );
}
