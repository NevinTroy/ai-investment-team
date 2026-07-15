"use client";

import { useEffect, useRef, useState } from "react";
import Avatar from "./Avatar";
import AgentsCard from "./AgentsCard";
import PdfSection from "./PdfSection";
import DeckExtractCard from "./DeckExtractCard";
import FollowupCard from "./FollowupCard";
import NetworkPanel from "./NetworkPanel";
import SynthesisCard from "./SynthesisCard";
import ComparisonCard from "./ComparisonCard";
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

  // compare/retrieve runs stream `agents: []` in their `start` event, so an
  // empty selectedAgents array marks a non-committee run — no agent cards, just
  // a single answer/comparison after one backend call.
  const isNonCommitteeRun =
    Array.isArray(state.selectedAgents) && state.selectedAgents.length === 0;

  const showAgents =
    (state.phase === "running" || state.phase === "done") &&
    !state.rejectedReason &&
    !isNonCommitteeRun &&
    Object.keys(state.agents).length + (state.phase === "running" ? 1 : 0) > 0;

  // Show a live "working" indicator while a request is in flight and there is no
  // agent committee to display — i.e. the pre-routing check, or the whole
  // running phase of a compare/retrieve run (which has no per-agent updates).
  const showThinking =
    !state.rejectedReason &&
    !state.errorMessage &&
    (state.phase === "checking" || (state.phase === "running" && !showAgents));

  // Prefer a live progress message streamed from the backend (compare/retrieve
  // emit these); fall back to a phase-based label.
  const thinkingLabel =
    state.statusText ||
    (state.phase === "checking" ? "Reviewing your question…" : "Working through the committee's data…");

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

          {/* Intermediate "extracted from your deck" section for upload runs. */}
          {state.deckExtract && <DeckExtractCard deck={state.deckExtract} />}

          {showThinking && (
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
                  {thinkingLabel}
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

          {/* Side-by-side table for comparison runs. */}
          {state.phase === "done" && state.comparison && !state.rejectedReason && !state.errorMessage && (
            <ComparisonCard comparison={state.comparison} />
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
