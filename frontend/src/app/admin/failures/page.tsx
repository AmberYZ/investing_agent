import { CancelPendingIngestButton } from "./CancelPendingIngestButton";
import { RequeueErrorIngestButton } from "./RequeueErrorIngestButton";
import { IngestJobsLive } from "./IngestJobsLive";

export default function FailuresPage() {
  return (
    <>
      <div className="flex items-center justify-between gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ingest jobs</h1>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            All ingest jobs: queued, in progress, done, and failed. Failed jobs can be requeued for retry.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <CancelPendingIngestButton />
            <RequeueErrorIngestButton />
          </div>
        </div>
      </div>

      <IngestJobsLive />
    </>
  );
}
