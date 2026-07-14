"use client";

import Avatar from "./Avatar";
import { renderText } from "@/lib/gcal";
import type { Synthesis } from "@/lib/types";

// Direct answer for narrow (single-analyst) runs — rendered as an assistant
// message instead of an investment memo.
export default function SynthesisCard({ synthesis }: { synthesis: Synthesis }) {
  return (
    <div className="asst-row">
      <Avatar />
      <div className="asst-body">
        <div className="asst-text" style={{ marginBottom: synthesis.key_points?.length ? 10 : 0 }}>
          <b dangerouslySetInnerHTML={{ __html: renderText(synthesis.headline) }} />
          {synthesis.answer && (
            <div style={{ marginTop: 6 }} dangerouslySetInnerHTML={{ __html: renderText(synthesis.answer) }} />
          )}
        </div>
        {synthesis.key_points?.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 18, color: "#a8a8ad", fontSize: 14, lineHeight: 1.6 }}>
            {synthesis.key_points.map((pt, i) => (
              <li key={i} dangerouslySetInnerHTML={{ __html: renderText(pt) }} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
