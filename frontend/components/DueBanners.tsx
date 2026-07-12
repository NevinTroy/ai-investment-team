"use client";

import type { Followup } from "@/lib/types";
import { fmtDateOnly } from "@/lib/gcal";

export default function DueBanners({
  followups,
  onRerun,
  onDismiss,
}: {
  followups: Followup[];
  onRerun: (f: Followup) => void;
  onDismiss: (f: Followup) => void;
}) {
  if (!followups.length) return null;
  return (
    <div id="due-banners">
      {followups.map((f) => (
        <div className="due-banner" key={f.id}>
          <div className="due-banner-text">
            It&apos;s time to rerun your research on <b>{f.company || f.question}</b> — you scheduled
            this for {fmtDateOnly(f.due_date)}.
          </div>
          <button className="followup-btn" onClick={() => onRerun(f)}>Rerun now</button>
          <button className="followup-btn dismiss" onClick={() => onDismiss(f)}>Dismiss</button>
        </div>
      ))}
    </div>
  );
}
