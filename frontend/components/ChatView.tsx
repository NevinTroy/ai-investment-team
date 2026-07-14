"use client";

import { useEffect, useRef, useState } from "react";
import Avatar from "./Avatar";
import AgentsCard from "./AgentsCard";
import PdfSection from "./PdfSection";
import FollowupCard from "./FollowupCard";
import NetworkPanel from "./NetworkPanel";
import SynthesisCard from "./SynthesisCard";
import type { AppState } from "@/app/page";

export default function ChatView({
  state,
  onToggleAgent,
  onSubmit,
}: {
  state: AppState;
  onToggleAgent: (id: string) => void;
  onSubmit: (question: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");

  const send = () => {
    const q = draft.trim();
    if (!q) return;
    setDraft("");
    onSubmit(q);
  };

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

          {/* Direct answer for narrow runs (no memo). */}
          {state.phase === "done" && state.synthesis && !state.rejectedReason && !state.errorMessage && (
            <SynthesisCard synthesis={state.synthesis} />
          )}

          {showWatchlistCard && (
            <FollowupCard chatId={state.chatId} company={state.company} question={state.query} />
          )}

          {/* Network graph only on a full investment run (narrow questions
              return no portfolio position). */}
          {state.phase === "done" && !state.rejectedReason && !state.errorMessage && state.newPos && (
            <NetworkPanel neighbors={state.neighbors} newPos={state.newPos} company={state.company} />
          )}
        </div>
      </div>

      <div id="composer">
        <div className="composer-inner">
          <input
            className="composer-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={state.company ? `Ask a follow-up about ${state.company}…` : "Ask a follow-up…"}
          />
          <button className="send-btn" onClick={send} disabled={!draft.trim()} aria-label="Send">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="19" x2="12" y2="5" />
              <polyline points="6 11 12 5 18 11" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
