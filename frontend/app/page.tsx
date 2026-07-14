"use client";

import { useCallback, useEffect, useReducer, useState } from "react";
import Sidebar from "@/components/Sidebar";
import Home from "@/components/Home";
import ChatView from "@/components/ChatView";
import DueBanners from "@/components/DueBanners";
import {
  completeFollowup,
  dismissFollowup,
  getChat,
  listChats,
  listDueFollowups,
  streamAnalysis,
} from "@/lib/api";
import type {
  AgentRowState,
  AnalyzeEvent,
  ChatSummary,
  Followup,
  MemoData,
  Neighbor,
  Synthesis,
} from "@/lib/types";

export interface AppState {
  phase: "home" | "checking" | "running" | "done";
  chatId: string | null;
  query: string;
  company: string;
  agents: Record<string, AgentRowState>;
  expanded: string | null;
  memoData: MemoData | null;
  synthesis: Synthesis | null;
  neighbors: Neighbor[];
  newPos: [number, number] | null;
  selectedAgents: string[] | null; // node names picked by the orchestrator; null → show all
  fromHistory: boolean;
  rejectedReason: string | null;
  errorMessage: string | null;
  pendingFollowupId: string | null;
}

const initialState: AppState = {
  phase: "home",
  chatId: null,
  query: "",
  company: "",
  agents: {},
  expanded: null,
  memoData: null,
  synthesis: null,
  neighbors: [],
  newPos: null,
  selectedAgents: null,
  fromHistory: false,
  rejectedReason: null,
  errorMessage: null,
  pendingFollowupId: null,
};

type Action =
  | { type: "reset" }
  | { type: "submit"; question: string }
  | { type: "sse"; ev: AnalyzeEvent }
  | { type: "toggleAgent"; id: string }
  | { type: "setPendingFollowup"; id: string }
  | { type: "networkError" }
  | { type: "loadedChat"; state: Partial<AppState> };

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "reset":
      return { ...initialState };

    case "submit":
      // pendingFollowupId survives so reruns can be marked done on start
      return {
        ...initialState,
        phase: "checking",
        query: action.question,
        pendingFollowupId: state.pendingFollowupId,
      };

    case "toggleAgent":
      return { ...state, expanded: state.expanded === action.id ? null : action.id };

    case "setPendingFollowup":
      return { ...state, pendingFollowupId: action.id };

    case "networkError":
      return { ...state, phase: "done", errorMessage: "Could not reach the server. Is it running?" };

    case "loadedChat":
      return { ...initialState, fromHistory: true, ...action.state };

    case "sse": {
      const ev = action.ev;
      switch (ev.type) {
        case "start":
          return {
            ...state,
            phase: "running",
            company: ev.company || state.company,
            chatId: ev.chat_id || state.chatId,
            selectedAgents: ev.agents || null,
            pendingFollowupId: null, // side effect (completeFollowup) fired by the caller
          };
        case "agent_update": {
          const prev = state.agents[ev.agent] || { status: "pending", ticker: "", report: "" };
          const isDone = (ev.status || "").toLowerCase() === "done";
          let report = prev.report;
          if (ev.analysis) {
            try {
              const parsed = JSON.parse(ev.analysis);
              report = parsed.reasoning || ev.analysis;
            } catch {
              report = ev.analysis;
            }
          }
          return {
            ...state,
            agents: {
              ...state.agents,
              [ev.agent]: {
                status: isDone ? "done" : "running",
                ticker: ev.ticker || prev.ticker,
                report,
              },
            },
          };
        }
        case "complete": {
          const ana = ev.data?.analysis || {};
          return {
            ...state,
            phase: "done",
            memoData: (ana.investment_memo as MemoData) || null,
            synthesis: ev.synthesis || null,
            company: ev.company || state.company,
            chatId: ev.chat_id || state.chatId,
            neighbors: ev.neighbors || [],
            newPos: ev.new_pos || null,
          };
        }
        case "rejected":
          return {
            ...state,
            phase: "done",
            chatId: ev.chat_id || state.chatId,
            rejectedReason: ev.reason || "Please ask about investing in a specific company.",
          };
        case "error":
          return { ...state, phase: "done", errorMessage: ev.message || "Unknown error" };
      }
    }
  }
}

export default function Page() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [dueFollowups, setDueFollowups] = useState<Followup[]>([]);

  const refreshChats = useCallback(() => {
    listChats().then(setChats).catch(() => {});
  }, []);

  useEffect(() => {
    refreshChats();
    listDueFollowups().then(setDueFollowups).catch(() => {});
  }, [refreshChats]);

  // Dev-only: /?stub=watchlist renders a fake done-state so the follow-up
  // card can be exercised without burning a live analysis. Anchored to the
  // most recent completed chat so scheduling writes a real followup row.
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    if (new URLSearchParams(window.location.search).get("stub") !== "watchlist") return;
    listChats().then((rows) => {
      const done = rows.find((c) => c.status === "done");
      dispatch({
        type: "loadedChat",
        state: {
          phase: "done",
          fromHistory: false,
          chatId: done?.id || null,
          query: done?.question || "Should we invest in StubCo?",
          company: done?.company || "StubCo",
          agents: {},
          memoData: { recommendation: "watchlist", recommendation_headline: "Watchlist" },
        },
      });
    });
  }, []);

  const submit = useCallback(
    (question: string, pendingFollowupId?: string) => {
      const q = question.trim();
      if (!q) return;
      if (pendingFollowupId) dispatch({ type: "setPendingFollowup", id: pendingFollowupId });
      dispatch({ type: "submit", question: q });

      let followupToComplete = pendingFollowupId || state.pendingFollowupId || null;
      streamAnalysis(
        q,
        (ev) => {
          if (ev.type === "start" && followupToComplete) {
            completeFollowup(followupToComplete, ev.chat_id || null);
            followupToComplete = null;
          }
          dispatch({ type: "sse", ev });
          if (ev.type === "complete" || ev.type === "rejected") refreshChats();
        },
        () => dispatch({ type: "networkError" }),
      );
    },
    [state.pendingFollowupId, refreshChats],
  );

  const loadChat = useCallback(async (chatId: string) => {
    const chat = await getChat(chatId);
    if (!chat) return;

    const ana = chat.analysis || {};
    // Narrow (single-analyst) runs have no memo — keep memoData null so the
    // PDF/watchlist sections don't render on reload.
    const memo = (ana.investment_memo as MemoData) || null;
    const deck = chat.deck;

    const agents: Record<string, AgentRowState> = {};
    for (const key of Object.keys(ana)) {
      const block = ana[key] as Record<string, unknown>;
      agents[`${key}_agent`] = {
        status: "done",
        ticker: "",
        report: (block.reasoning as string) || JSON.stringify(block, null, 2),
      };
    }

    const loaded: Partial<AppState> = {
      phase: "done",
      chatId: chat.id,
      query: chat.question || "",
      company: chat.company || "",
      agents,
      memoData:
        memo && deck
          ? { ...memo, presentation_url: deck.public_url, edit_path: memo.edit_path || deck.edit_path || undefined }
          : memo,
      synthesis: chat.synthesis || null,
      neighbors: chat.network_snapshot?.neighbors || [],
      newPos: chat.network_snapshot?.new_pos || null,
      selectedAgents: Object.keys(agents).length ? Object.keys(agents) : null,
    };

    if (chat.status === "rejected") {
      const assistantMsg = (chat.messages || []).find((m) => m.role === "assistant");
      loaded.rejectedReason = chat.error_message || assistantMsg?.content || "Not an investment question.";
      loaded.agents = {};
      loaded.memoData = null;
    } else if (chat.status === "error") {
      loaded.errorMessage = chat.error_message || "Analysis failed.";
      loaded.agents = {};
      loaded.memoData = null;
    }

    dispatch({ type: "loadedChat", state: loaded });
  }, []);

  const handleRerun = useCallback(
    (f: Followup) => {
      setDueFollowups((prev) => prev.filter((x) => x.id !== f.id));
      submit(f.question, f.id);
    },
    [submit],
  );

  const handleDismiss = useCallback((f: Followup) => {
    dismissFollowup(f.id);
    setDueFollowups((prev) => prev.filter((x) => x.id !== f.id));
  }, []);

  return (
    <div id="app">
      <Sidebar
        chats={chats}
        activeChatId={state.chatId}
        onSelect={loadChat}
        onNewChat={() => dispatch({ type: "reset" })}
      />
      <div id="main">
        {state.phase === "home" ? (
          <Home onSubmit={(q) => submit(q)}>
            <DueBanners followups={dueFollowups} onRerun={handleRerun} onDismiss={handleDismiss} />
          </Home>
        ) : (
          <ChatView
            state={state}
            onToggleAgent={(id) => dispatch({ type: "toggleAgent", id })}
            onSubmit={(q) => submit(q)}
          />
        )}
      </div>
    </div>
  );
}
