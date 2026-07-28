"use client";

export type NarrativeBriefingData = {
  summary?: string | null;
  investment_relevance?: string | null;
  what_changed?: string | null;
  change_narrative_ids?: number[];
  trending_sub_themes?: string[];
  inflection_alert?: string | null;
};

function renderMarkdownish(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-zinc-900 dark:text-zinc-50">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

export function NarrativeBriefing({
  data,
  compact = false,
  showDetail = true,
}: {
  data: NarrativeBriefingData | null | undefined;
  compact?: boolean;
  /** When false, only show bottom line + what moved (memo body elsewhere). */
  showDetail?: boolean;
}) {
  if (!data) {
    return (
      <div className="rounded-lg bg-zinc-50/80 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900/50 dark:text-zinc-400">
        No analyst memo yet — generated on the next aggregation run.
      </div>
    );
  }

  const relevance = (data.investment_relevance || "").trim();
  const changed = (data.what_changed || "").trim();
  const summary = (data.summary || "").trim();
  const pending = /memo pending|aggregation run/i.test(summary);

  if (!summary && !relevance && !changed) {
    return (
      <div className="rounded-lg bg-zinc-50/80 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900/50 dark:text-zinc-400">
        No analyst memo yet.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50/80 px-3 py-2.5 dark:border-zinc-800 dark:bg-zinc-900/50">
      <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Analyst memo
      </div>

      {showDetail && summary && (
        <div
          className={`mt-1.5 whitespace-pre-line leading-relaxed text-zinc-800 dark:text-zinc-100 ${
            compact ? "text-xs" : "text-sm"
          } ${pending ? "text-zinc-500 dark:text-zinc-400" : ""}`}
        >
          {renderMarkdownish(summary)}
        </div>
      )}

      {!pending && (relevance || changed) && (
        <div className="mt-2 space-y-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
          {relevance && (
            <div>
              <div className="text-[11px] font-semibold text-zinc-700 dark:text-zinc-300">
                Bottom line
              </div>
              <p className="mt-0.5 text-xs leading-relaxed text-zinc-700 dark:text-zinc-200">
                {renderMarkdownish(relevance)}
              </p>
            </div>
          )}
          {changed && (
            <div>
              <div className="text-[11px] font-semibold text-zinc-700 dark:text-zinc-300">
                What moved
              </div>
              <p className="mt-0.5 text-xs leading-relaxed text-zinc-700 dark:text-zinc-200">
                {renderMarkdownish(changed)}
              </p>
            </div>
          )}
        </div>
      )}

      {!showDetail && !pending && (relevance || changed) && !summary && (
        <div className="mt-1.5 space-y-2">
          {relevance && (
            <p className="text-xs leading-relaxed text-zinc-700 dark:text-zinc-200">
              {renderMarkdownish(relevance)}
            </p>
          )}
          {changed && (
            <p className="text-xs leading-relaxed text-zinc-700 dark:text-zinc-200">
              {renderMarkdownish(changed)}
            </p>
          )}
        </div>
      )}

      {data.inflection_alert && !pending && (
        <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
          Inflection: {data.inflection_alert}
        </p>
      )}
      {data.trending_sub_themes && data.trending_sub_themes.length > 0 && !pending && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {data.trending_sub_themes.map((st) => (
            <span
              key={st}
              className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200"
            >
              {st}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
