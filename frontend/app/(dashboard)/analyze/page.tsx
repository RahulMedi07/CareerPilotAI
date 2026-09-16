'use client';

import { useEffect, useState } from 'react';
import { FileUp, Zap } from 'lucide-react';

import { AgentTraceViewer } from '@/components/dashboard/AgentTraceViewer';
import { AnalysisResults } from '@/components/dashboard/AnalysisResults';
import { ErrorMessage } from '@/components/shared/ErrorMessage';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { clearIndex, describeApiError, fullAnalysis, getIndexStatus, uploadResume } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { AnalysisResult, IndexStatus } from '@/types';

/** Mirrors `ALLOWED_EXTENSIONS` and `MAX_UPLOAD_SIZE_MB` in `backend/config.py`. */
const ACCEPTED = '.pdf,.docx,.txt,.md';
const MAX_BYTES = 10 * 1024 * 1024;

export default function AnalyzePage() {
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [uploadedName, setUploadedName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const [jobDescription, setJobDescription] = useState('');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusKey, setStatusKey] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    let cancelled = false;

    getIndexStatus()
      .then((status) => {
        if (!cancelled) setIndexStatus(status);
      })
      .catch(() => {
        // A failed status read is not worth a red banner on arrival; the
        // analysis call will report the outage properly if the backend is
        // really down.
        if (!cancelled) setIndexStatus(null);
      });

    return () => {
      cancelled = true;
    };
  }, [statusKey]);

  /**
   * Upload one file, wherever it came from.
   *
   * Split out of the change handler so the drop target and the file picker
   * share it. A dropped file must go through exactly the same size and
   * extension checks as a picked one; two code paths would eventually
   * disagree, and the lenient one would be the one users found.
   */
  const uploadFile = async (file: File) => {
    const name = file.name.toLowerCase();
    if (!ACCEPTED.split(',').some((ext) => name.endsWith(ext.trim()))) {
      setError(`${file.name} is not a .pdf, .docx, .txt or .md file.`);
      return;
    }

    // Checked here as well as on the server so the reader finds out before a
    // 10MB round trip, not after it.
    if (file.size > MAX_BYTES) {
      setError(`${file.name} is larger than the 10MB limit.`);
      return;
    }

    setUploading(true);
    setError(null);

    try {
      await uploadResume(file);
      setUploadedName(file.name);
      setStatusKey((key) => key + 1);
    } catch (err) {
      setError(describeApiError(err));
      setUploadedName(null);
    } finally {
      setUploading(false);
    }
  };

  const handleResumeUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    await uploadFile(file);
    // Reset the input so re-picking the same file fires a change event.
    event.target.value = '';
  };

  const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) await uploadFile(file);
  };

  const handleClearIndex = async () => {
    setError(null);
    try {
      await clearIndex();
      setUploadedName(null);
      setStatusKey((key) => key + 1);
    } catch (err) {
      setError(describeApiError(err));
    }
  };

  const handleAnalyze = async () => {
    if (!jobDescription.trim()) return;

    setAnalyzing(true);
    setError(null);

    try {
      // No `resumeText` argument: the pipeline reads the indexed resume. The
      // second parameter is for scoring raw text that was never indexed.
      const result = await fullAnalysis(jobDescription.trim());
      setAnalysis(result);
    } catch (err) {
      setError(describeApiError(err));
      setAnalysis(null);
    } finally {
      setAnalyzing(false);
    }
  };

  const indexed = indexStatus?.resume_indexed ?? false;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">
          <span className="gradient-text">Analyse a job</span>
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Paste a job advert and it is scored against your resume, step by step, so you can see how
          the result was reached.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardContent className="space-y-6">
            <section>
              <h2 className="mb-3 font-medium">Your resume</h2>

              <div
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                className={cn(
                  'rounded-lg border-2 border-dashed p-6 text-center transition-colors',
                  dragging ? 'border-primary bg-muted/50' : 'hover:border-blue-400',
                )}
              >
                <input
                  type="file"
                  accept={ACCEPTED}
                  onChange={handleResumeUpload}
                  className="sr-only"
                  id="resume-upload"
                  disabled={uploading}
                />
                <label htmlFor="resume-upload" className="cursor-pointer">
                  <FileUp className="mx-auto mb-2 size-7 text-muted-foreground" aria-hidden />
                  <p className="text-sm font-medium">
                    {uploading
                      ? 'Uploading…'
                      : dragging
                        ? 'Drop it here'
                        : 'Drop your resume here, or click to choose'}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    .pdf, .docx, .txt or .md · up to 10MB
                  </p>
                </label>
              </div>

              {uploadedName ? (
                <p className="mt-2 rounded bg-green-50 p-2 text-sm text-green-700 dark:bg-green-950/30 dark:text-green-300">
                  Saved {uploadedName}
                </p>
              ) : null}

              {indexStatus ? (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="text-muted-foreground">
                    {indexed
                      ? 'Your resume is saved and will be used for this analysis.'
                      : 'No resume yet — the analysis will have nothing to compare the job against.'}
                  </span>
                  {indexed ? (
                    <Button variant="link" size="sm" className="h-auto p-0" onClick={handleClearIndex}>
                      Remove resume
                    </Button>
                  ) : null}
                </div>
              ) : null}

              {/*
                Worth stating outright. The index is one shared collection, so
                a second upload is added to the first rather than replacing it,
                and the score would then be measured against a blend of two
                resumes. Until per-document collections exist, the user needs
                to know that clearing first is the deliberate step.
              */}
              {indexed ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  Uploading another file adds to your saved resume rather than replacing it, so the
                  score would be measured against both together. Remove the first one to swap.
                </p>
              ) : null}
            </section>

            <section>
              <h2 className="mb-3 font-medium">Job description</h2>
              <Textarea
                placeholder="Paste the whole advert — responsibilities and requirements included…"
                value={jobDescription}
                onChange={(event) => setJobDescription(event.target.value)}
                className="min-h-64"
                aria-label="Job description"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {jobDescription.trim().length} characters. A short advert gives less to work with,
                and the confidence in the result drops accordingly.
              </p>
            </section>

            {error ? <ErrorMessage message={error} /> : null}

            <Button
              onClick={handleAnalyze}
              disabled={analyzing || !jobDescription.trim()}
              className="w-full gap-2"
              size="lg"
            >
              <Zap className="size-4" aria-hidden />
              {analyzing ? 'Analysing…' : 'Run analysis'}
            </Button>

            {!indexed && indexStatus ? (
              <p className="text-xs text-muted-foreground">
                You can still run this without a resume — it will read the advert and report zero
                matched skills, which reflects having no resume saved, not a judgement of you.
              </p>
            ) : null}
          </CardContent>
        </Card>

        <div>
          {analyzing ? (
            <LoadingSpinner message="Working through the advert. This takes a few seconds." />
          ) : analysis ? (
            <AnalysisResults analysis={analysis} />
          ) : (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                Upload a resume, paste an advert, then run the analysis. Your result, and how it
                was reached, appear here.
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {analysis ? (
        <AgentTraceViewer
          trace={analysis.execution_trace}
          totalMs={analysis.total_analysis_time_ms}
          nodesFailed={analysis.nodes_failed}
        />
      ) : null}
    </div>
  );
}
