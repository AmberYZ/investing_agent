import Link from "next/link";
import { ExtractedTextView } from "./ExtractedTextView";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Document = {
  id: number;
  filename: string;
  summary?: string | null;
  num_pages?: number | null;
  source_type: string;
  source_name: string;
  source_uri?: string | null;
  received_at: string;
  published_at?: string | null;
  gcs_raw_uri: string;
  gcs_text_uri?: string | null;
  download_url?: string | null;
  text_download_url?: string | null;
};

async function getDocument(id: string): Promise<Document> {
  const res = await fetch(`${API_BASE}/documents/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch document: ${res.status}`);
  return res.json();
}

async function getDocumentText(id: string): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/documents/${id}/text`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.text();
  } catch {
    return null;
  }
}

type DocumentExcerpt = { quote: string; page: number | null };

function buildFallbackSummary(text: string | null): string | null {
  if (!text) return null;
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  const sentences = normalized.split(/(?<=[.!?])\s+/);
  const preview = sentences.slice(0, 3).join(" ");
  const clipped = preview.slice(0, 600).trim();
  return clipped || null;
}

async function getDocumentExcerpts(id: string): Promise<DocumentExcerpt[]> {
  try {
    const res = await fetch(`${API_BASE}/documents/${id}/excerpts`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return data?.excerpts ?? [];
  } catch {
    return [];
  }
}

export default async function DocumentPage(
  props: { params: Promise<{ id: string }>; searchParams: Promise<{ [key: string]: string | string[] | undefined }> }
) {
  const { id } = await props.params;
  const searchParams = await props.searchParams;
  const highlightParam = searchParams?.highlight;
  // Next.js already decodes searchParams; do NOT double-decode (breaks on quotes with %)
  const highlightQuote =
    typeof highlightParam === "string" && highlightParam
      ? highlightParam
      : undefined;

  const [doc, extractedText, excerptsFromApi] = await Promise.all([
    getDocument(id),
    getDocumentText(id),
    getDocumentExcerpts(id),
  ]);

  const fallbackSummary = !doc.summary ? buildFallbackSummary(extractedText) : null;

  const excerpts =
    highlightQuote && !excerptsFromApi.some((e) => e.quote.trim() === highlightQuote.trim())
      ? [...excerptsFromApi, { quote: highlightQuote, page: null }]
      : excerptsFromApi;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 dark:bg-black dark:text-zinc-50">
      <main className="mx-auto w-full max-w-3xl px-6 py-10">
        <div className="flex items-center justify-between gap-6">
          <div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              <Link href="/" className="hover:underline">
                Themes
              </Link>{" "}
              / <span className="font-mono text-[11px]">doc {doc.id}</span>
            </div>
            <h1 className="mt-2 text-xl font-semibold tracking-tight">{doc.filename}</h1>
            <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
              {doc.source_name} · {doc.source_type} ·{" "}
              {new Date(doc.received_at).toLocaleString()}
            </p>
          </div>
          {doc.download_url && (
            <a
              href={doc.download_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center rounded-full bg-zinc-900 px-4 py-2 text-xs font-medium text-zinc-50 shadow-sm transition hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Open Original
            </a>
          )}
        </div>

        <div className="mt-6 space-y-4">
          <div className="rounded-xl border border-zinc-200 bg-white p-5 text-sm dark:border-zinc-800 dark:bg-zinc-950">
            <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Key takeaways
            </div>
            <p className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400">
              Main points from this document
            </p>
            <div className="mt-2 text-sm text-zinc-700 dark:text-zinc-200">
              {doc.summary ?? fallbackSummary ?? "No key takeaways stored yet."}
            </div>
          </div>

          <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Extracted text
            </div>
            <p className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400">
              Key sentences used as evidence are highlighted
            </p>
            <div className="mt-3 max-h-[60vh] overflow-y-auto rounded border border-zinc-100 bg-zinc-50/50 p-4 text-sm leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-200">
              {extractedText ? (
                <ExtractedTextView
                  text={extractedText}
                  excerpts={excerpts}
                  scrollToHighlight={!!highlightQuote}
                />
              ) : (
                "No extracted text available for this document."
              )}
            </div>
          </div>

          <div className="rounded-xl border border-zinc-200 bg-white p-5 text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200">
            <div className="font-semibold text-zinc-500 dark:text-zinc-400">Metadata</div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Pages
                </dt>
                <dd className="mt-1 text-xs">{doc.num_pages ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Source URI
                </dt>
                <dd className="mt-1 break-all text-xs">
                  {doc.source_uri ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Raw object URI
                </dt>
                <dd className="mt-1 break-all text-xs">{doc.gcs_raw_uri}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                  Text object URI
                </dt>
                <dd className="mt-1 break-all text-xs">
                  {doc.gcs_text_uri ?? "—"}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </main>
    </div>
  );
}

