"use client";

import Avatar from "./Avatar";
import type { MemoData } from "@/lib/types";

export default function PdfSection({ memo, company }: { memo: MemoData; company: string }) {
  const rec = (memo.recommendation || "invest").toLowerCase();
  const recLabel = rec === "invest" ? "PROCEED" : rec === "pass" ? "PASS" : "WATCHLIST";
  const recColor = rec === "invest" ? "#6cc08e" : rec === "pass" ? "#e07070" : "#e0a060";
  const pdfUrl = memo.presentation_url || null;
  const editUrl = memo.edit_path || null;
  const fileLabel = pdfUrl
    ? pdfUrl.split("/").pop()!.split("?")[0]
    : `Investment-Memo-${company.replace(/\s+/g, "-")}.pdf`;

  return (
    <div className="asst-row pdf-section">
      <Avatar />
      <div className="asst-body">
        <div className="asst-text">
          All agents finished. I compiled the findings into an investment memo — recommendation:{" "}
          <b style={{ color: recColor }}>{recLabel}</b>.
        </div>

        {pdfUrl ? (
          <>
            <div className="pdf-file-chip">
              <div className="pdf-icon">PDF</div>
              <div className="pdf-file-meta">
                <div className="pdf-file-name">{fileLabel}</div>
                <div className="pdf-file-sub">Presenton export</div>
              </div>
              <a className="pdf-download-btn" href={pdfUrl} target="_blank" rel="noopener noreferrer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                Open PDF
              </a>
            </div>

            <div className="pdf-viewer">
              <div className="pdf-viewer-bar">
                <span>{fileLabel}</span>
                {editUrl && (
                  <a
                    className="pdf-download-btn"
                    href={editUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ height: 28, fontSize: 12 }}
                  >
                    Edit in Presenton
                  </a>
                )}
              </div>
              <iframe className="pdf-embed" src={pdfUrl} title="Investment Memo PDF" />
            </div>
          </>
        ) : (
          <div className="pdf-viewer">
            <div className="pdf-unavailable">
              Presenton did not return a PDF link. Check the investment memo agent output for details.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
