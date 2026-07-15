"use client";

import { useEffect, useRef, useState } from "react";

const PLACEHOLDER_COMPANIES = [
  "Gamma",
  "Stripe",
  "Notion",
  "Figma",
  "Anthropic",
  "Databricks",
  "Canva",
  "Vercel",
  "Ramp",
  "Perplexity",
];

export default function Home({
  onSubmit,
  onDeck,
  children,
}: {
  onSubmit: (question: string) => void;
  onDeck?: (file: File) => void;
  children?: React.ReactNode;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [hasText, setHasText] = useState(false);

  useEffect(() => {
    const id = setInterval(
      () => setPlaceholderIdx((i) => (i + 1) % PLACEHOLDER_COMPANIES.length),
      2500,
    );
    return () => clearInterval(id);
  }, []);

  const submit = () => {
    const q = (taRef.current?.value || "").trim();
    if (q) onSubmit(q);
  };

  return (
    <div id="home">
      {children}
      <div className="logo-mark">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/app_icon.png" alt="Archer" />
      </div>
      <div className="hero-text">
        I&apos;m Archer, your AI investment team.
        <br />
        Deploy the team to make investment decisions.
      </div>
      <div className="home-input-wrap">
        {/* Fake placeholder: real placeholders can't animate, so the rotating
            company name rises in via a keyed span over the empty textarea. */}
        {!hasText && (
          <div className="ph-overlay" aria-hidden="true">
            Ask anything — e.g. Should I invest in{" "}
            <span className="ph-word" key={placeholderIdx}>
              {PLACEHOLDER_COMPANIES[placeholderIdx]}?
            </span>
          </div>
        )}
        <textarea
          ref={taRef}
          rows={2}
          aria-label="Ask an investment question"
          onInput={(e) => setHasText(e.currentTarget.value.length > 0)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="home-input-actions">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              ref={fileRef}
              type="file"
              accept=".pptx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onDeck?.(f);
                e.target.value = ""; // allow re-uploading the same file
              }}
            />
            <button
              type="button"
              className="deck-upload-btn"
              title="Upload a pitch deck (.pptx or .pdf)"
              onClick={() => fileRef.current?.click()}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                background: "transparent",
                border: "1px solid #2c2c32",
                color: "#a8a8ad",
                borderRadius: 8,
                padding: "6px 10px",
                fontSize: 12.5,
                cursor: "pointer",
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Upload deck
            </button>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
            <button className="send-btn" onClick={submit}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="6 11 12 5 18 11" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
