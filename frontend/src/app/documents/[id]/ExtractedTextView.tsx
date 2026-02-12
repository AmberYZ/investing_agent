"use client";

import React, { useEffect, useRef } from "react";

type Excerpt = { quote: string; page: number | null };

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Normalize text for approximate matching: lowercase, collapse whitespace, drop punctuation. */
function normalizeForApproxMatch(s: string): { normalized: string; indexMap: number[] } {
  const normalizedChars: string[] = [];
  const indexMap: number[] = [];
  let lastWasSpace = false;

  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (/\s/.test(ch)) {
      if (!lastWasSpace) {
        normalizedChars.push(" ");
        indexMap.push(i);
        lastWasSpace = true;
      }
      continue;
    }
    const lower = ch.toLowerCase();
    if (/[a-z0-9]/i.test(lower)) {
      normalizedChars.push(lower);
      indexMap.push(i);
      lastWasSpace = false;
    } else {
      // Skip punctuation and symbols entirely for approximate match.
      continue;
    }
  }

  return { normalized: normalizedChars.join(""), indexMap };
}

/** Fallback: approximate match ignoring punctuation and compressing whitespace. */
function findApproximateRanges(text: string, quote: string): [number, number][] {
  const { normalized: normText, indexMap } = normalizeForApproxMatch(text);
  const { normalized: normQuote } = normalizeForApproxMatch(quote);
  const ranges: [number, number][] = [];

  if (!normQuote) return ranges;

  let start = 0;
  // Find all non-overlapping approximate matches.
  while (true) {
    const idx = normText.indexOf(normQuote, start);
    if (idx === -1) break;
    const endIdx = idx + normQuote.length - 1;
    const startOrig = indexMap[idx];
    const endOrigBase = indexMap[endIdx];
    if (typeof startOrig === "number" && typeof endOrigBase === "number") {
      ranges.push([startOrig, endOrigBase + 1]);
    }
    start = idx + normQuote.length;
  }

  return ranges;
}

/** Build non-overlapping [start, end] ranges (end exclusive) for excerpt matches in text. */
function buildHighlightRanges(text: string, excerpts: Excerpt[]): [number, number][] {
  const ranges: [number, number][] = [];
  for (const { quote } of excerpts) {
    const trimmed = (quote || "").trim();
    if (!trimmed) continue;
    // First try an exact-ish regex match (flexible whitespace).
    const pattern = escapeRegex(trimmed).replace(/\s+/g, "\\s+");
    const re = new RegExp(pattern, "gi");
    let m: RegExpExecArray | null;
    let foundForThisQuote = false;
    while ((m = re.exec(text)) !== null) {
      ranges.push([m.index, m.index + m[0].length]);
      foundForThisQuote = true;
    }
    // If we didn't find any matches, fall back to approximate matching that
    // ignores punctuation and hyphenation differences.
    if (!foundForThisQuote) {
      const approx = findApproximateRanges(text, trimmed);
      if (approx.length > 0) {
        ranges.push(...approx);
      }
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const [s, e] of ranges) {
    if (merged.length && s <= merged[merged.length - 1][1]) {
      merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], e);
    } else {
      merged.push([s, e]);
    }
  }
  return merged;
}

/** Split text into segments: [normal, highlighted, normal, ...]. */
function splitByHighlights(text: string, ranges: [number, number][]): { highlight: boolean; text: string }[] {
  if (ranges.length === 0) return [{ highlight: false, text }];
  const out: { highlight: boolean; text: string }[] = [];
  let last = 0;
  for (const [s, e] of ranges) {
    if (s > last) out.push({ highlight: false, text: text.slice(last, s) });
    out.push({ highlight: true, text: text.slice(s, e) });
    last = e;
  }
  if (last < text.length) out.push({ highlight: false, text: text.slice(last) });
  return out;
}

type Block = { type: "paragraph"; text: string } | { type: "table"; rows: string[][] };

function detectBlocks(text: string): Block[] {
  const lines = text.split(/\r?\n/);
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const cells = line.split(/\s{2,}|\t+/);
    const numCols = cells.length;

    if (numCols >= 2 && cells.some((c) => c.trim().length > 0)) {
      const tableRows: string[][] = [];
      while (i < lines.length) {
        const rowLine = lines[i];
        const rowCells = rowLine.split(/\s{2,}|\t+/);
        if (rowCells.length >= 2 && rowCells.some((c) => c.trim().length > 0)) {
          tableRows.push(rowCells.map((c) => c.trim()));
          i++;
        } else {
          break;
        }
      }
      if (tableRows.length >= 2) {
        blocks.push({ type: "table", rows: tableRows });
        continue;
      }
      for (const row of tableRows) {
        blocks.push({ type: "paragraph", text: row.join(" ").trim() });
      }
      continue;
    }

    const paraLines: string[] = [];
    while (i < lines.length) {
      const rowLine = lines[i];
      const rowCells = rowLine.split(/\s{2,}|\t+/);
      if (rowCells.length >= 2 && rowCells.some((c) => c.trim().length > 0)) {
        break;
      }
      paraLines.push(rowLine);
      i++;
    }
    const para = paraLines.join("\n").trim();
    if (para) blocks.push({ type: "paragraph", text: para });
  }

  return blocks;
}

function HighlightedContent({
  text,
  excerpts,
  as: Tag = "span",
  className,
}: {
  text: string;
  excerpts: Excerpt[];
  as?: "p" | "span";
  className?: string;
}) {
  const ranges = buildHighlightRanges(text, excerpts);
  const segments = splitByHighlights(text, ranges);
  return (
    <Tag className={className}>
      {segments.map((seg, idx) =>
        seg.highlight ? (
          <mark
            key={idx}
            className="rounded bg-amber-200/80 px-0.5 font-medium text-amber-900 dark:bg-amber-400/40 dark:text-amber-100"
          >
            {seg.text}
          </mark>
        ) : (
          <span key={idx}>{seg.text}</span>
        )
      )}
    </Tag>
  );
}

function HighlightedParagraph({
  text,
  excerpts,
}: {
  text: string;
  excerpts: Excerpt[];
}) {
  return (
    <HighlightedContent
      text={text}
      excerpts={excerpts}
      as="p"
      className="mb-3 last:mb-0"
    />
  );
}

export function ExtractedTextView({
  text,
  excerpts,
  scrollToHighlight = false,
}: {
  text: string;
  excerpts: Excerpt[];
  scrollToHighlight?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!scrollToHighlight || !containerRef.current) return;
    const firstMark = containerRef.current.querySelector("mark");
    if (firstMark) {
      firstMark.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [scrollToHighlight, text, excerpts]);

  const blocks = detectBlocks(text);

  return (
    <div ref={containerRef} className="space-y-4">
      {blocks.map((block, idx) => {
        if (block.type === "paragraph") {
          return (
            <HighlightedParagraph
              key={idx}
              text={block.text}
              excerpts={excerpts}
            />
          );
        }
        return (
          <div key={idx} className="my-4 overflow-x-auto rounded border border-zinc-200 dark:border-zinc-700">
            <table className="min-w-full border-collapse text-sm">
              <tbody>
                {block.rows.map((row, ri) => (
                  <tr
                    key={ri}
                    className={
                      ri === 0
                        ? "border-b border-zinc-200 bg-zinc-100/80 font-medium dark:border-zinc-700 dark:bg-zinc-800/80"
                        : "border-b border-zinc-100 dark:border-zinc-800"
                    }
                  >
                    {row.map((cell, ci) => (
                      <td
                        key={ci}
                        className="border-r border-zinc-200 px-3 py-2 last:border-r-0 dark:border-zinc-700"
                      >
                        <HighlightedContent text={cell} excerpts={excerpts} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
