"use client";

import Avatar from "./Avatar";
import { renderText } from "@/lib/gcal";
import type { Comparison } from "@/lib/types";

// Colour a 0-10 score: red (low) -> amber -> green (high).
function scoreColor(v: number): string {
  if (v >= 7.5) return "#6cc08e";
  if (v >= 5) return "#d3b673";
  return "#e07070";
}

// Side-by-side comparison for "compare" runs (A vs B, or a whole sector),
// rendered as an assistant message: a verdict banner + a scorecard table.
export default function ComparisonCard({ comparison }: { comparison: Comparison }) {
  const { headline, winner, rationale, dimensions, rows } = comparison;

  return (
    <div className="asst-row">
      <Avatar />
      <div className="asst-body" style={{ width: "100%" }}>
        <div className="asst-text" style={{ marginBottom: 12 }}>
          <b dangerouslySetInnerHTML={{ __html: renderText(headline) }} />
          {rationale && (
            <div style={{ marginTop: 6 }} dangerouslySetInnerHTML={{ __html: renderText(rationale) }} />
          )}
        </div>

        <div style={{ overflowX: "auto", border: "1px solid #26262b", borderRadius: 10 }}>
          <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#161619" }}>
                <th style={{ textAlign: "left", padding: "10px 12px", color: "#a8a8ad", fontWeight: 600 }}>
                  Company
                </th>
                {dimensions.map((d) => (
                  <th key={d} style={{ textAlign: "center", padding: "10px 12px", color: "#a8a8ad", fontWeight: 600 }}>
                    {d}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isWinner = winner && row.company.toLowerCase() === winner.toLowerCase();
                return (
                  <tr key={row.company} style={{ borderTop: "1px solid #26262b" }}>
                    <td style={{ padding: "10px 12px", verticalAlign: "top" }}>
                      <div style={{ fontWeight: 600, color: "#e7e7ea", display: "flex", alignItems: "center", gap: 6 }}>
                        {row.company}
                        {isWinner && (
                          <span
                            style={{
                              fontSize: 10,
                              fontWeight: 700,
                              color: "#6cc08e",
                              border: "1px solid #2f5c43",
                              borderRadius: 4,
                              padding: "1px 5px",
                              textTransform: "uppercase",
                              letterSpacing: 0.4,
                            }}
                          >
                            Winner
                          </span>
                        )}
                      </div>
                      {row.highlight && (
                        <div style={{ marginTop: 4, fontSize: 12, color: "#8fbf9f" }}>+ {row.highlight}</div>
                      )}
                      {row.concern && (
                        <div style={{ marginTop: 2, fontSize: 12, color: "#c98b8b" }}>− {row.concern}</div>
                      )}
                    </td>
                    {dimensions.map((d) => {
                      const v = row.scores?.[d];
                      return (
                        <td key={d} style={{ padding: "10px 12px", textAlign: "center", verticalAlign: "top" }}>
                          {typeof v === "number" ? (
                            <span style={{ color: scoreColor(v), fontWeight: 600 }}>{v.toFixed(1)}</span>
                          ) : (
                            <span style={{ color: "#57575c" }}>—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
