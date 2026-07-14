// Shapes returned by the FastAPI backend (committee/api.py + committee/persistence.py).

export const AGENT_ORDER = [
  "competitive_intelligence_agent",
  "founder_analyzer_agent",
  "investment_memo_agent",
  "market_analyzer_agent",
  "product_analyst_agent",
  "risk_analyst_agent",
] as const;

export type AgentId = (typeof AGENT_ORDER)[number];

export const AGENT_DISPLAY: Record<AgentId, string> = {
  competitive_intelligence_agent: "Competitive Intelligence",
  founder_analyzer_agent: "Founder Analyzer",
  investment_memo_agent: "Investment Memo",
  market_analyzer_agent: "Market Analyzer",
  product_analyst_agent: "Product Analyst",
  risk_analyst_agent: "Risk Analyst",
};

export type AgentStatus = "pending" | "running" | "done";

export interface AgentRowState {
  status: AgentStatus;
  ticker: string;
  report: string;
}

export interface MemoData {
  recommendation?: string;
  recommendation_headline?: string;
  presentation_url?: string;
  edit_path?: string;
  [key: string]: unknown;
}

// Direct answer produced for narrow (single-analyst) runs that have no memo.
export interface Synthesis {
  headline: string;
  answer: string;
  key_points: string[];
}

export interface Neighbor {
  id: number;
  name: string;
  sector: string;
  summary: string;
  location: string;
  site: string;
  similarity: number;
  x: number;
  y: number;
}

export interface NetworkNode {
  id: number;
  name: string;
  sector: string;
  summary: string;
  location: string;
  site: string;
  x: number;
  y: number;
}

export interface Deck {
  id: string;
  chat_id: string;
  storage_path: string;
  public_url: string;
  edit_path: string | null;
  file_name: string | null;
}

export interface ChatSummary {
  id: string;
  title: string | null;
  company: string | null;
  question: string;
  status: "running" | "done" | "rejected" | "error";
  created_at: string;
}

export interface ChatDetail extends ChatSummary {
  analysis: Record<string, Record<string, unknown>> | null;
  network_snapshot: { neighbors: Neighbor[]; new_pos: [number, number] | null } | null;
  synthesis: Synthesis | null;
  error_message: string | null;
  deck: Deck | null;
  messages: { role: "user" | "assistant"; content: string; created_at: string }[];
}

export interface Followup {
  id: string;
  chat_id: string;
  company: string;
  question: string;
  due_date: string;
  status: "pending" | "done" | "dismissed";
  rerun_chat_id: string | null;
}

// SSE events streamed from POST /api/analyze
export type AnalyzeEvent =
  | { type: "start"; company: string; question: string; chat_id: string | null; agents?: string[] }
  | { type: "agent_update"; agent: string; display_name: string; ticker: string; status: string; analysis: string | null }
  | { type: "complete"; data: { analysis?: Record<string, MemoData> }; company: string; neighbors: Neighbor[]; new_pos: [number, number] | null; synthesis: Synthesis | null; chat_id: string | null }
  | { type: "rejected"; reason: string; chat_id: string | null }
  | { type: "error"; message: string };
