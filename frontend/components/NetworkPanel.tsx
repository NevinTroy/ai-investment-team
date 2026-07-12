"use client";

import { useEffect, useRef, useState } from "react";
import Avatar from "./Avatar";
import { getNetwork } from "@/lib/api";
import type { Neighbor, NetworkNode } from "@/lib/types";

// Fetched once per page load — the portfolio dataset is static.
let _nodesCache: NetworkNode[] | null = null;

const H = 520;
const PAD = 32;

export default function NetworkPanel({
  neighbors,
  newPos,
  company,
}: {
  neighbors: Neighbor[];
  newPos: [number, number] | null;
  company: string;
}) {
  const [nodes, setNodes] = useState<NetworkNode[] | null>(_nodesCache);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);

  useEffect(() => {
    if (_nodesCache) return;
    getNetwork()
      .then((n) => {
        _nodesCache = n;
        setNodes(n);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !nodes) return;

    const W = canvas.offsetWidth;
    canvas.width = W * window.devicePixelRatio;
    canvas.height = H * window.devicePixelRatio;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";

    const ctx = canvas.getContext("2d")!;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    const toX = (x: number) => PAD + x * (W - PAD * 2);
    const toY = (y: number) => PAD + y * (H - PAD * 2);

    ctx.fillStyle = "#0f0f11";
    ctx.fillRect(0, 0, W, H);

    const neighborMap = new Map(neighbors.map((n) => [n.id, n]));

    // Edges from the new company to its neighbours
    if (newPos) {
      const nx = toX(newPos[0]);
      const ny = toY(newPos[1]);
      neighbors.forEach((n) => {
        const alpha = 0.15 + n.similarity * 0.55;
        ctx.beginPath();
        ctx.moveTo(nx, ny);
        ctx.lineTo(toX(n.x), toY(n.y));
        ctx.strokeStyle = `rgba(108,192,142,${alpha})`;
        ctx.lineWidth = 1 + n.similarity * 1.5;
        ctx.stroke();
      });
    }

    // All portfolio nodes
    nodes.forEach((node) => {
      const x = toX(node.x);
      const y = toY(node.y);
      const nb = neighborMap.get(node.id);

      if (nb) {
        ctx.beginPath();
        ctx.arc(x, y, 7 + nb.similarity * 4, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(47,107,79,${0.2 + nb.similarity * 0.25})`;
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(x, y, nb ? 4.5 : 3, 0, Math.PI * 2);
      ctx.fillStyle = nb ? `rgba(108,192,142,${0.6 + nb.similarity * 0.4})` : "rgba(120,120,130,0.45)";
      ctx.fill();

      if (nb) {
        ctx.font = "500 10px 'Helvetica Neue', sans-serif";
        ctx.fillStyle = "rgba(200,200,210,0.85)";
        ctx.fillText(node.name, x + 7, y + 4);
      }
    });

    // The analyzed company's node
    if (newPos) {
      const nx = toX(newPos[0]);
      const ny = toY(newPos[1]);
      const grad = ctx.createRadialGradient(nx, ny, 4, nx, ny, 20);
      grad.addColorStop(0, "rgba(58,125,91,0.55)");
      grad.addColorStop(1, "rgba(58,125,91,0)");
      ctx.beginPath();
      ctx.arc(nx, ny, 20, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(nx, ny, 7, 0, Math.PI * 2);
      ctx.fillStyle = "#6cc08e";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(nx, ny, 7, 0, Math.PI * 2);
      ctx.strokeStyle = "#eafff2";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.font = "600 11px 'Helvetica Neue', sans-serif";
      ctx.fillStyle = "#eafff2";
      ctx.fillText(company, nx + 10, ny + 4);
    }

    // Neighbor-chip hover ring
    if (highlightId !== null) {
      const node = nodes.find((n) => n.id === highlightId);
      if (node) {
        ctx.beginPath();
        ctx.arc(toX(node.x), toY(node.y), 9, 0, Math.PI * 2);
        ctx.strokeStyle = "#eafff2";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    // Tooltip on hover
    const tooltip = tooltipRef.current!;
    let hoveredId: number | null = null;

    canvas.onmousemove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      let hit: (NetworkNode & { _isNew?: boolean }) | null = null;
      let hitDist = Infinity;

      nodes.forEach((node) => {
        const d = Math.hypot(mx - toX(node.x), my - toY(node.y));
        const r = neighborMap.has(node.id) ? 7 : 5;
        if (d < r + 4 && d < hitDist) {
          hit = node;
          hitDist = d;
        }
      });

      if (newPos) {
        const d = Math.hypot(mx - toX(newPos[0]), my - toY(newPos[1]));
        if (d < 12 && d < hitDist) {
          hit = { id: -1, name: company, sector: "", summary: "", location: "", site: "", x: 0, y: 0, _isNew: true };
          hitDist = d;
        }
      }

      if (hit && hit.id !== hoveredId) {
        hoveredId = hit.id;
        tooltip.querySelector<HTMLElement>(".network-tooltip-name")!.textContent = hit.name;
        tooltip.querySelector<HTMLElement>(".network-tooltip-sector")!.textContent = hit.sector || "";
        tooltip.querySelector<HTMLElement>(".network-tooltip-loc")!.textContent = hit.location || "";
        const sim = hit._isNew ? null : neighborMap.get(hit.id);
        tooltip.querySelector<HTMLElement>(".network-tooltip-sim")!.textContent = sim
          ? `similarity: ${(sim.similarity * 100).toFixed(1)}%`
          : "";
        const words = (hit.summary || "").split(" ");
        tooltip.querySelector<HTMLElement>(".network-tooltip-summary")!.textContent =
          words.length > 30 ? words.slice(0, 30).join(" ") + "…" : hit.summary || "";

        const panelRect = canvas.parentElement!.getBoundingClientRect();
        let tx = e.clientX - panelRect.left + 14;
        const ty = e.clientY - panelRect.top - 20;
        const ttW = 280;
        if (tx + ttW > panelRect.width - 10) tx = e.clientX - panelRect.left - ttW - 14;
        tooltip.style.left = tx + "px";
        tooltip.style.top = ty + "px";
        tooltip.classList.add("visible");
        canvas.style.cursor = "pointer";
      } else if (!hit) {
        hoveredId = null;
        tooltip.classList.remove("visible");
        canvas.style.cursor = "crosshair";
      }
    };

    canvas.onmouseleave = () => {
      tooltip.classList.remove("visible");
      hoveredId = null;
    };
  }, [nodes, neighbors, newPos, company, highlightId]);

  if (!nodes) return null;

  return (
    <div className="asst-row network-section">
      <Avatar />
      <div className="asst-body">
        <div className="asst-text">
          Here&apos;s where <b>{company}</b> sits in the Summit portfolio network — based on
          semantic similarity across sector and business model.
        </div>
        <div className="network-card">
          <div className="network-header">
            <span className="network-header-label">Portfolio similarity map</span>
            <span className="network-header-sub">
              {nodes.length} companies · {neighbors.length} nearest neighbours
            </span>
          </div>
          <div className="network-canvas-wrap">
            <canvas ref={canvasRef} height={H} id="network-canvas" />
            <div className="network-tooltip" ref={tooltipRef}>
              <div className="network-tooltip-name" />
              <div className="network-tooltip-sector" />
              <div className="network-tooltip-loc" />
              <div className="network-tooltip-sim" />
              <div className="network-tooltip-summary" />
            </div>
          </div>
          {neighbors.length > 0 && (
            <div className="neighbor-list">
              <div className="neighbor-list-label">NEAREST NEIGHBOURS</div>
              <div className="neighbor-chips">
                {neighbors.map((n) => (
                  <div
                    className="neighbor-chip"
                    key={n.id}
                    onMouseEnter={() => setHighlightId(n.id)}
                    onMouseLeave={() => setHighlightId(null)}
                  >
                    <span>{n.name}</span>
                    <span className="neighbor-chip-sim">{(n.similarity * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
