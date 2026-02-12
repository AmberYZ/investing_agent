"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type Node = { id: number; canonical_label: string; mention_count: number };
type Edge = { theme_id_a: number; theme_id_b: number; weight: number };

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const NODE_RADIUS_MIN = 10;
const NODE_RADIUS_MAX = 22;
const LABEL_FONT = "system-ui, sans-serif";

function getNodeRadius(mentionCount: number): number {
  const s = Math.sqrt(Math.max(0, mentionCount) + 1);
  return Math.min(NODE_RADIUS_MAX, Math.max(NODE_RADIUS_MIN, s * 1.5));
}

/** Abbreviate theme label for on-dot display; longer text for larger nodes. */
function abbreviateLabel(label: string, radius: number): string {
  const full = (label ?? "").trim();
  if (!full) return "";
  const words = full.split(/\s+/);
  if (radius >= 18) {
    const two = words.slice(0, 2).join(" ");
    return two.length > 14 ? two.slice(0, 12) + "…" : two || full.slice(0, 12) + "…";
  }
  if (radius >= 14) {
    const one = words[0] ?? full;
    return one.length > 10 ? one.slice(0, 8) + "…" : one;
  }
  if (radius >= 11) {
    const one = words[0] ?? full;
    return one.length > 6 ? one.slice(0, 5) + "…" : one;
  }
  const initials = words.slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return initials || full.slice(0, 2);
}

export function ThemeNetworkGraph({
  nodes,
  edges,
  height = 640,
}: {
  nodes: Node[];
  edges: Edge[];
  height?: number;
}) {
  const router = useRouter();
  const [hoverNodeId, setHoverNodeId] = useState<string | null>(null);
  const fgRef = useRef<{
    d3Force?: (name: string, fn?: unknown) => unknown;
    d3ReheatSimulation?: () => void;
    zoomToFit?: (duration?: number) => void;
  } | null>(null);
  const graphData = useMemo(() => {
    const graphNodes = nodes.map((n) => ({
      id: String(n.id),
      canonical_label: n.canonical_label,
      mention_count: n.mention_count,
      _radius: getNodeRadius(n.mention_count),
    }));
    const graphLinks = edges.map((e) => ({
      source: String(e.theme_id_a),
      target: String(e.theme_id_b),
      value: e.weight,
    }));
    return { nodes: graphNodes, links: graphLinks };
  }, [nodes, edges]);

  const neighborSet = useMemo(() => {
    if (!hoverNodeId) return new Set<string>();
    const set = new Set<string>([hoverNodeId]);
    for (const link of graphData.links) {
      const src = typeof link.source === "object" ? (link.source as { id?: string }).id : link.source;
      const tgt = typeof link.target === "object" ? (link.target as { id?: string }).id : link.target;
      if (String(src) === hoverNodeId) set.add(String(tgt));
      if (String(tgt) === hoverNodeId) set.add(String(src));
    }
    return set;
  }, [hoverNodeId, graphData.links]);

  // Spread layout: stronger repulsion, longer link distance, optional collision so nodes don’t overlap
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg?.d3Force || !fg?.d3ReheatSimulation || graphData.nodes.length === 0) return;
    const charge = fg.d3Force("charge") as { strength?: (v: number) => unknown };
    if (charge?.strength) charge.strength(-480);
    const link = fg.d3Force("link") as { distance?: (v: number) => unknown };
    if (link?.distance) link.distance(130);
    fg.d3ReheatSimulation();
    import("d3-force-3d")
      .then((d3) => {
        const getCollisionRadius = (node: { _radius?: number }) =>
          ((node as { _radius?: number })._radius ?? NODE_RADIUS_MIN) + 58;
        fg.d3Force?.("collide", d3.forceCollide(getCollisionRadius).iterations(3));
        fg.d3ReheatSimulation?.();
      })
      .catch(() => {});
  }, [graphData]);

  const nodeCanvasObject = useCallback(
    (
      node: { x?: number; y?: number; id?: string | number; canonical_label?: string; _radius?: number },
      ctx: CanvasRenderingContext2D,
      _globalScale: number
    ) => {
      if (node.x == null || node.y == null) return;
      const fullLabel = String(node.canonical_label ?? node.id ?? "");
      const radius = (node as { _radius?: number })._radius ?? NODE_RADIUS_MIN;
      const id = String(node.id ?? "");
      const isHighlight = hoverNodeId === null || neighborSet.has(id);
      const isHovered = hoverNodeId === id;

      // Circle: highlight when hovered or when showing relationships
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
      if (isHovered) {
        ctx.fillStyle = "rgba(34, 197, 94, 1)";
        ctx.strokeStyle = "rgba(22, 163, 74, 1)";
        ctx.lineWidth = 2.5;
      } else if (isHighlight && hoverNodeId) {
        ctx.fillStyle = "rgba(34, 197, 94, 0.92)";
        ctx.strokeStyle = "rgba(34, 197, 94, 0.98)";
        ctx.lineWidth = 2;
      } else {
        ctx.fillStyle = "rgba(148, 163, 184, 0.5)";
        ctx.strokeStyle = "rgba(100, 116, 139, 0.6)";
        ctx.lineWidth = 1;
      }
      ctx.fill();
      ctx.stroke();

      // Abbreviated label on the dot (centered)
      const abbrev = abbreviateLabel(fullLabel, radius);
      if (abbrev) {
        const fontSize = Math.max(7, Math.min(11, radius * 0.65));
        ctx.font = `${fontSize}px ${LABEL_FONT}`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = isHighlight ? "#fff" : "rgba(255,255,255,0.9)";
        ctx.fillText(abbrev, node.x, node.y);
      }
    },
    [hoverNodeId, neighborSet]
  );

  if (graphData.nodes.length === 0) return null;

  return (
    <div className="w-full" style={{ height }}>
      <ForceGraph2D
        ref={fgRef as unknown as React.MutableRefObject<undefined>}
        graphData={graphData}
        nodeId="id"
        nodeCanvasObject={nodeCanvasObject}
        nodeCanvasObjectMode="replace"
        nodeVal={(n) => (n as { _radius?: number })._radius ?? NODE_RADIUS_MIN}
        nodePointerAreaPaint={(node, color, ctx) => {
          const radius = (node as { _radius?: number })._radius ?? NODE_RADIUS_MIN;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, radius + 24, 0, 2 * Math.PI);
          ctx.fill();
        }}
        nodeLabel={(n: { canonical_label?: string; id?: string | number }) =>
          n.canonical_label ?? String(n.id ?? "")
        }
        onNodeHover={(n, _prev) => setHoverNodeId(n != null ? String((n as { id?: string | number }).id) : null)}
        linkColor={(link: { source?: unknown; target?: unknown }) => {
          if (!hoverNodeId) return "rgba(100, 116, 139, 0.55)";
          const src = typeof link.source === "object" ? (link.source as { id?: string }).id : link.source;
          const tgt = typeof link.target === "object" ? (link.target as { id?: string }).id : link.target;
          const involved = String(src) === hoverNodeId || String(tgt) === hoverNodeId;
          return involved ? "rgba(34, 197, 94, 0.85)" : "rgba(148, 163, 184, 0.2)";
        }}
        linkWidth={(l: { value?: number; source?: unknown; target?: unknown }) => {
          const base = Math.max(1.2, Math.log2((l.value ?? 0) + 1) * 1.3);
          if (!hoverNodeId) return base;
          const src = typeof l.source === "object" ? (l.source as { id?: string }).id : l.source;
          const tgt = typeof l.target === "object" ? (l.target as { id?: string }).id : l.target;
          const involved = String(src) === hoverNodeId || String(tgt) === hoverNodeId;
          return involved ? base * 1.4 : base * 0.5;
        }}
        linkDirectionalParticles={0}
        linkCurvature={0.08}
        onNodeClick={(n: { id?: string | number }) => {
          if (n.id != null) router.push(`/themes/${n.id}`);
        }}
        onEngineStop={() => fgRef.current?.zoomToFit?.(400)}
        d3AlphaDecay={0.025}
        d3VelocityDecay={0.35}
        cooldownTicks={150}
      />
    </div>
  );
}
