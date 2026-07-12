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
  children,
}: {
  onSubmit: (question: string) => void;
  children?: React.ReactNode;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
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
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#7c7c82" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="3" width="6" height="11" rx="3" />
              <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
            </svg>
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
