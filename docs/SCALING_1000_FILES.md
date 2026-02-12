# Scaling to 1000+ Files

Recommendations before pointing the ingest client at a folder with 1000+ PDFs.

## 1. Rate limiting the LLM (recommended)

The worker processes **one document at a time** and makes one LLM call per document. To avoid hitting OpenAI (or other provider) rate limits (e.g. requests per minute, RPM):

- Set **`LLM_DELAY_AFTER_REQUEST_SECONDS`** in `.env` (e.g. `1.0`). The worker will sleep that many seconds after each extraction call.
- Example: with 60 RPM limit, use at least `1.0`; for 3,500 RPM you can leave it at `0` or use a small value like `0.2`.

```bash
# In repo root .env
LLM_DELAY_AFTER_REQUEST_SECONDS=1.0
```

## 2. Existing behavior that already helps

- **Single worker**: Only one ingest job runs at a time, so you never send many concurrent LLM requests.
- **Retries**: LLM extraction uses exponential backoff (up to 5 attempts) on failures, so transient 503/429 can succeed on retry.
- **Ingest client**: It uploads one file per request and waits for the response, so the API is not hit with 1000 concurrent connections.

## 3. Optional: limit how many files are queued per poll

The ingest client currently processes **every new PDF** in the watch folder each poll. With 1000 files, the first run will queue 1000 jobs (one HTTP request per file, sequential). That’s fine; the worker will work through the queue. If you prefer to grow the queue gradually (e.g. cap at 50 new files per poll), you can add a limit in the ingest client loop (e.g. `for p in pdfs[:50]:` and break after that many new ingest calls). Not required for correctness.

## 4. Database and storage

- **SQLite**: Fine for 1000 docs. For much larger scale or concurrent API usage, consider switching to PostgreSQL (`DATABASE_URL=postgresql+psycopg://...`).
- **Local storage**: Ensure `LOCAL_STORAGE_DIR` has enough disk space for 1000+ PDFs and extracted text artifacts.

## 5. Stuck “processing” jobs

If the worker crashes during a job, that job can stay in `processing` forever. To recover, you can either:

- Re-queue from the admin UI if you add a “Reset to queued” action, or
- Manually update the DB: set `status = 'queued'` and `started_at = NULL` for jobs stuck in `processing` for a long time.

## Summary

- Set **`LLM_DELAY_AFTER_REQUEST_SECONDS=1.0`** (or higher) when running 1000+ docs with a rate-limited LLM.
- Keep a single worker; no need to add latency between API *endpoints*—only between LLM calls.
- Optionally cap new files per poll in the ingest client if you want to throttle how fast the queue grows.
