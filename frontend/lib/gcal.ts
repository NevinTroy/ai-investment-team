export function fmtDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return (
    d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " +
    d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  );
}

export function fmtDateOnly(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00"); // noon avoids timezone day-shift
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function isoDateFromToday(days: number, months = 0): string {
  const d = new Date();
  if (months) d.setMonth(d.getMonth() + months);
  if (days) d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function gcalUrl(company: string, isoDate: string, question: string): string {
  const start = isoDate.replaceAll("-", "");
  const next = new Date(isoDate + "T12:00:00Z");
  next.setUTCDate(next.getUTCDate() + 1);
  const end = next.toISOString().slice(0, 10).replaceAll("-", "");
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: `Rerun Archer research: ${company}`,
    dates: `${start}/${end}`, // all-day event; end date is exclusive
    details: `Open Archer and rerun the watchlist analysis for ${company}.\nOriginal question: ${question}`,
  });
  return "https://calendar.google.com/calendar/render?" + params.toString();
}

// Markdown-lite renderer from the original frontend: escape HTML, convert
// **bold**/*italic*, and insert a zero-width non-joiner after every $ so
// MathJax/KaTeX browser extensions cannot enter math mode.
export function renderText(s: string): string {
  if (!s) return "";
  return escHtml(s)
    .replace(/\$(?=\S)/g, "$‌")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\*(.+?)\*/g, "<i>$1</i>");
}

export function escHtml(s: string): string {
  if (!s) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
