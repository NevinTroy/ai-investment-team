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
 * POST to an SSE endpoint and stream `data: {...}` events back through `onEvent`.
 * (EventSource doesn't support POST bodies, so this reads the response body as a
 * stream and parses the lines — same approach as the original vanilla frontend.)
 */
async function readSSE(res: Response, onEvent: (ev: AnalyzeEvent) => void): Promise<void> {
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

async function streamSSE(
  url: string,
  body: unknown,
  onEvent: (ev: AnalyzeEvent) => void,
  onNetworkError: () => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    onNetworkError();
    return;
  }
  await readSSE(res, onEvent);
}

/** POST /api/analyze and stream the SSE events back through `onEvent`. */
export function streamAnalysis(
  question: string,
  onEvent: (ev: AnalyzeEvent) => void,
  onNetworkError: () => void,
): Promise<void> {
  return streamSSE("/api/analyze", { question }, onEvent, onNetworkError);
}

/**
 * Upload a .pptx/.pdf deck to /api/analyze-deck (multipart) and stream the SSE
 * events — including the intermediate `deck_extracted` event — back through
 * `onEvent`. On an HTTP error (bad type / too large) surfaces a synthetic error
 * event so the caller renders it like any other failure.
 */
export async function streamDeckAnalysis(
  file: File,
  onEvent: (ev: AnalyzeEvent) => void,
  onNetworkError: () => void,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch("/api/analyze-deck", { method: "POST", body: form });
  } catch {
    onNetworkError();
    return;
  }
  if (!res.ok) {
    let detail = `Upload failed (${res.status}).`;
    try {
      const j = await res.json();
      if (j?.detail) detail = j.detail;
    } catch {
      /* keep default */
    }
    onEvent({ type: "error", message: detail });
    return;
  }
  await readSSE(res, onEvent);
}

/**
 * Run a scheduled watchlist revisit: re-research the company and stream a diff
 * against its original analysis (no deck). The backend marks the follow-up done.
 */
export function streamRerun(
  followupId: string,
  onEvent: (ev: AnalyzeEvent) => void,
  onNetworkError: () => void,
): Promise<void> {
  return streamSSE(`/api/followups/${followupId}/rerun`, {}, onEvent, onNetworkError);
}
