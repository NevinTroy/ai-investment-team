"use client";

import { useRef, useState } from "react";
import Avatar from "./Avatar";
import { createFollowup } from "@/lib/api";
import { fmtDateOnly, gcalUrl, isoDateFromToday } from "@/lib/gcal";

type CardState = "idle" | "error" | "declined" | `scheduled:${string}`;

export default function FollowupCard({
  chatId,
  company,
  question,
}: {
  chatId: string | null;
  company: string;
  question: string;
}) {
  const [cardState, setCardState] = useState<CardState>("idle");
  const dateRef = useRef<HTMLInputElement>(null);

  if (cardState === "declined") return null;

  const schedule = async (dueDate: string) => {
    const ok =
      !!chatId &&
      (await createFollowup({ chat_id: chatId, company, question, due_date: dueDate }));
    if (ok) {
      window.open(gcalUrl(company, dueDate, question), "_blank", "noopener");
      setCardState(`scheduled:${dueDate}`);
    } else {
      setCardState("error");
    }
  };

  let body: React.ReactNode;
  if (cardState.startsWith("scheduled:")) {
    const date = cardState.slice("scheduled:".length);
    body = (
      <div className="followup-card">
        <div className="followup-confirm">
          Follow-up scheduled for {fmtDateOnly(date)} — I&apos;ll remind you here, and the calendar
          event is your backup.
        </div>
      </div>
    );
  } else if (cardState === "error") {
    body = (
      <div className="followup-card">
        <div className="followup-card-text" style={{ color: "#e07070" }}>
          Could not save the follow-up. Is Supabase configured and the followups table created?
        </div>
      </div>
    );
  } else {
    body = (
      <div className="followup-card">
        <div className="followup-card-title">Worth revisiting</div>
        <div className="followup-card-text">
          <b>{company}</b> landed on the watchlist. Want me to rerun this research later? Pick a
          date — I&apos;ll add it to your Google Calendar and prompt you to rerun when the day comes.
        </div>
        <div className="followup-options">
          <button className="followup-btn" onClick={() => schedule(isoDateFromToday(14))}>In 2 weeks</button>
          <button className="followup-btn" onClick={() => schedule(isoDateFromToday(0, 1))}>In 1 month</button>
          <button className="followup-btn" onClick={() => schedule(isoDateFromToday(0, 3))}>In 3 months</button>
          <input type="date" className="followup-date-input" ref={dateRef} min={isoDateFromToday(1)} />
          <button
            className="followup-btn"
            onClick={() => {
              const v = dateRef.current?.value;
              if (v) schedule(v);
            }}
          >
            Schedule
          </button>
          <button className="followup-btn dismiss" onClick={() => setCardState("declined")}>
            No thanks
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="asst-row">
      <Avatar />
      <div className="asst-body">{body}</div>
    </div>
  );
}
