"use client";

import { useState } from "react";
import Avatar from "./Avatar";
import type { DeckExtract } from "@/lib/types";

// Intermediate "here's what I pulled from your deck" section, shown after an
// upload and before/alongside the committee's analysis. Collapsed by default so
// it doesn't dominate the transcript; expand to read the per-slide/page text.
export default function DeckExtractCard({ deck }: { deck: DeckExtract }) {
  const [open, setOpen] = useState(false);
  const kindLabel = deck.kind === "pptx" ? "PowerPoint" : "PDF";
  const unit = deck.kind === "pptx" ? "slides" : "pages";
  const withText = deck.sections.length;
  const total = deck.total_units ?? withText;
  // If some slides/pages were image-only (no extractable text), say so instead
  // of implying the deck only had `withText` pages.
  const countLabel =
    total > withText
      ? `${withText} of ${total} ${unit} had extractable text`
      : `${total} ${unit}`;

  return (
    <div className="asst-row">
      <Avatar />
      <div className="asst-body" style={{ width: "100%" }}>
        <div className="asst-text" style={{ marginBottom: 10 }}>
          I read your {kindLabel} deck{deck.filename ? ` (${deck.filename})` : ""} —{" "}
          {countLabel}, {deck.char_count.toLocaleString()} characters extracted.
          {deck.company && (
            <>
              {" "}It pitches <b>{deck.company}</b>
              {deck.sector ? ` (${deck.sector})` : ""}. Running the committee on it now.
            </>
          )}
        </div>

        {deck.summary && (
          <div
            style={{
              fontSize: 13,
              color: "#c7c7cc",
              background: "#141416",
              border: "1px solid #26262b",
              borderRadius: 10,
              padding: "10px 12px",
              marginBottom: 10,
            }}
          >
            {deck.summary}
          </div>
        )}

        <button
          onClick={() => setOpen((v) => !v)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            background: "transparent",
            border: "1px solid #2c2c32",
            color: "#a8a8ad",
            borderRadius: 8,
            padding: "5px 10px",
            fontSize: 12.5,
            cursor: "pointer",
          }}
        >
          <span style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .15s" }}>▸</span>
          {open ? "Hide" : "Show"} extracted text ({withText} {unit})
        </button>

        {open && (
          <div
            style={{
              marginTop: 10,
              maxHeight: 520,
              overflowY: "auto",
              border: "1px solid #26262b",
              borderRadius: 10,
              background: "#0f0f11",
            }}
          >
            {deck.sections.map((s, i) => (
              <div key={i} style={{ borderTop: i ? "1px solid #202024" : "none", padding: "10px 12px" }}>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.4, color: "#6cc08e", textTransform: "uppercase", marginBottom: 4 }}>
                  {s.label}
                </div>
                <div style={{ fontSize: 12.5, color: "#d0d0d4", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
                  {s.text}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
