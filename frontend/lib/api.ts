import type { AnalyzeEvent, ChatDetail, ChatSummary, Followup, NetworkNode } from "./types";

export async function listChats(): Promise<ChatSummary[]> {
  const res = await fetch("/api/chats");
  const json = await res.json();
  return json.chats || [];
}

export async function getChat(chatId: string): Promise<ChatDetail | null> {
  const res = await fetch(`/api/chats/${chatId}`);
  if (!res.ok) return null;
  return res.json();
}

export async function getNetwork(): Promise<NetworkNode[]> {
  const res = await fetch("/api/network");
  const json = await res.json();
  return json.nodes || [];
}

export async function listDueFollowups(): Promise<Followup[]> {
  const res = await fetch("/api/followups/due");
  const json = await res.json();
  return json.followups || [];
}

export async function createFollowup(input: {
  chat_id: string;
  company: string;
  question: string;
  due_date: string;
}): Promise<boolean> {
  try {
    const res = await fetch("/api/followups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function completeFollowup(followupId: string, rerunChatId: string | null): void {
  fetch(`/api/followups/${followupId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rerun_chat_id: rerunChatId }),
  }).catch(() => {});
}

export function dismissFollowup(followupId: string): void {
  fetch(`/api/followups/${followupId}/dismiss`, { method: "POST" }).catch(() => {});
}

/**
 * POST /api/analyze and stream the SSE events back through `onEvent`.
 * (EventSource doesn't support POST bodies, so this reads the response
 * body as a stream and parses `data: {...}` lines — same approach as the
 * original vanilla frontend.)
 */
export async function streamAnalysis(
  question: string,
  onEvent: (ev: AnalyzeEvent) => void,
  onNetworkError: () => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  } catch {
    onNetworkError();
    return;
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch {
          /* ignore malformed lines */
        }
      }
    }
  }
}
