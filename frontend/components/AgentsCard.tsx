"use client";

import { AGENT_DISPLAY, AGENT_ORDER, type AgentId, type AgentRowState } from "@/lib/types";
import { renderText } from "@/lib/gcal";

export default function AgentsCard({
  agents,
  selectedAgents,
  expanded,
  onToggle,
}: {
  agents: Record<string, AgentRowState>;
  selectedAgents: string[] | null;
  expanded: string | null;
  onToggle: (id: string) => void;
}) {
  // Only show the agents the orchestrator selected (null → all, e.g. old chats)
  const order = selectedAgents
    ? AGENT_ORDER.filter((id) => selectedAgents.includes(id))
    : [...AGENT_ORDER];

  const doneCount = Object.values(agents).filter((a) => a.status === "done").length;

  return (
    <div className="agents-card">
      <div className="agents-header">
        <span className="agents-header-label">Agents deployed</span>
        <span className="agents-header-count">
          {doneCount}/{order.length} done
        </span>
      </div>
      {order.map((id) => {
        const a = agents[id] || { status: "pending", ticker: "", report: "" };
        const isExpanded = expanded === id;
        const isDone = a.status === "done";
        const statusColor = isDone ? "#6cc08e" : a.status === "running" ? "#c5c5c9" : "#5c5c62";
        const statusLabel = isDone ? "Done" : a.status === "running" ? "Running…" : "Queued";

        return (
          <div className="agent-row" key={id}>
            <div
              className={`agent-row-inner${isDone ? " clickable" : ""}`}
              onClick={() => isDone && onToggle(id)}
            >
              <div className="status-icon">
                {a.status === "pending" ? (
                  <div className="icon-pending" />
                ) : a.status === "running" ? (
                  <div className="icon-running" />
                ) : (
                  <div className="icon-done">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#dff3e8" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                )}
              </div>
              <div className="agent-info">
                <div className="agent-name-row">
                  <span className="agent-name">{AGENT_DISPLAY[id as AgentId]}</span>
                  <span className="agent-pill">{a.ticker || "…"}</span>
                </div>
                {a.report && isExpanded && (
                  <div
                    className="agent-report open"
                    dangerouslySetInnerHTML={{ __html: renderText(a.report) }}
                  />
                )}
              </div>
              <div className="agent-right">
                <span className="agent-status-label" style={{ color: statusColor }}>
                  {statusLabel}
                </span>
                {isDone && (
                  <span
                    style={{
                      transform: isExpanded ? "rotate(180deg)" : "rotate(0)",
                      display: "inline-block",
                      transition: "transform .2s",
                    }}
                  >
                    <svg className="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6a6a70" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
