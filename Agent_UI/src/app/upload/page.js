"use client";

import { useState, useRef, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  X,
  Bot,
} from "lucide-react";
import { getPresignedUrl, uploadFileToS3, notifyUploadComplete } from "@/services/api";

const ACCEPTED_TYPES = {
  "application/pdf": ".pdf",
  "text/plain": ".txt",
  "text/markdown": ".md",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
};

const ACCEPTED_EXTENSIONS = Object.values(ACCEPTED_TYPES).join(", ");

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | uploading | success | error
  const [progress, setProgress] = useState(0);
  const [objectKey, setObjectKey] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [jobStatusUrl, setJobStatusUrl] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  const inputRef = useRef(null);

  const validateFile = (f) => {
    if (!ACCEPTED_TYPES[f.type]) {
      return `Unsupported file type "${f.type}". Allowed: ${ACCEPTED_EXTENSIONS}`;
    }
    if (f.size > 50 * 1024 * 1024) {
      return "File exceeds the 50 MB limit.";
    }
    return null;
  };

  const selectFile = (f) => {
    const err = validateFile(f);
    if (err) {
      setErrorMessage(err);
      setStatus("error");
      setFile(null);
      return;
    }
    setFile(f);
    setStatus("idle");
    setErrorMessage(null);
    setObjectKey(null);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) selectFile(dropped);
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragActive(false), []);

  const handleFileInput = (e) => {
    const picked = e.target.files?.[0];
    if (picked) selectFile(picked);
    // Reset input so same file can be re-selected after clearing
    e.target.value = "";
  };

  const clearFile = () => {
    setFile(null);
    setStatus("idle");
    setErrorMessage(null);
    setObjectKey(null);
    setProgress(0);
  };

  const handleUpload = async () => {
    if (!file || status === "uploading") return;

    setStatus("uploading");
    setProgress(0);
    setErrorMessage(null);

    try {
      const { url, fields, object_key } = await getPresignedUrl(file.name, file.type);
      await uploadFileToS3(url, fields, file, setProgress);
      setObjectKey(object_key);

      // notify backend to enqueue ingestion
      try {
        const resp = await notifyUploadComplete(object_key);
        setJobId(resp.job_id || null);
        setJobStatusUrl(resp.status_url || null);
      } catch (err) {
        console.error("Failed to notify backend for ingestion:", err);
      }

      setStatus("success");
    } catch (err) {
      setErrorMessage(err.message || "Upload failed. Please try again.");
      setStatus("error");
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      {/* Header */}
      <header className="shrink-0 flex items-center gap-3 px-6 h-14 border-b border-border dark:border-border-dark bg-white dark:bg-[#09090b]">
        <div className="w-7 h-7 bg-primary rounded-lg flex items-center justify-center">
          <Bot className="w-3.5 h-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold text-foreground">Cortex</span>
        <span className="text-border dark:text-border-dark mx-1">/</span>
        <span className="text-sm text-muted">Upload Documents</span>
        <Link
          href="/"
          className="ml-auto flex items-center gap-1.5 text-sm text-muted hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Chat
        </Link>
      </header>

      {/* Main */}
      <main className="flex-1 flex items-start justify-center px-4 py-12 overflow-y-auto">
        <div className="w-full max-w-xl space-y-6">
          <div>
            <h1 className="text-xl font-semibold text-foreground">
              Upload Documents for RAG
            </h1>
            <p className="text-sm text-muted mt-1">
              Upload a file to store in S3 and index into the vector database so
              Cortex can search it.
            </p>
          </div>

          {/* Supported types */}
          <div className="flex flex-wrap gap-2">
            {Object.values(ACCEPTED_TYPES).map((ext) => (
              <span
                key={ext}
                className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[11px] font-medium"
              >
                {ext}
              </span>
            ))}
            <span className="px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-muted text-[11px]">
              Max 50 MB
            </span>
          </div>

          {/* Drop zone */}
          {!file && status !== "success" && (
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => inputRef.current?.click()}
              className={`
                relative flex flex-col items-center justify-center gap-3
                rounded-xl border-2 border-dashed px-8 py-14 cursor-pointer
                transition-colors
                ${
                  dragActive
                    ? "border-primary bg-primary/5"
                    : "border-border dark:border-border-dark hover:border-primary/50 hover:bg-primary/[0.02]"
                }
              `}
            >
              <div className="w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center">
                <Upload className="w-6 h-6 text-primary" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium text-foreground">
                  Drag &amp; drop a file here
                </p>
                <p className="text-xs text-muted mt-0.5">
                  or{" "}
                  <span className="text-primary underline underline-offset-2">
                    browse from your computer
                  </span>
                </p>
              </div>
              <input
                ref={inputRef}
                type="file"
                accept={Object.keys(ACCEPTED_TYPES).join(",")}
                onChange={handleFileInput}
                className="hidden"
              />
            </div>
          )}

          {/* Selected file card */}
          {file && status !== "success" && (
            <div className="rounded-xl border border-border dark:border-border-dark bg-surface dark:bg-surface-dark p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <FileText className="w-5 h-5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {file.name}
                  </p>
                  <p className="text-xs text-muted">{formatBytes(file.size)}</p>
                </div>
                {status !== "uploading" && (
                  <button
                    onClick={clearFile}
                    className="p-1.5 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800 text-muted hover:text-foreground transition-colors"
                    aria-label="Remove file"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>

              {/* Progress bar */}
              {status === "uploading" && (
                <div className="mt-4 space-y-1.5">
                  <div className="h-1.5 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-200"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="text-[11px] text-muted text-right">{progress}%</p>
                </div>
              )}
            </div>
          )}

          {/* Error banner */}
          {status === "error" && errorMessage && (
            <div className="flex items-start gap-3 rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/30 px-4 py-3">
              <XCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
              <p className="text-sm text-red-700 dark:text-red-400">{errorMessage}</p>
            </div>
          )}

          {/* Success state */}
          {status === "success" && (
            <div className="rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50 dark:bg-emerald-950/30 px-5 py-5 space-y-3">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-300">
                  Upload successful
                </p>
              </div>
              <p className="text-xs text-emerald-700 dark:text-emerald-400">
                The file has been uploaded to S3. It will be available for RAG
                search once the ingestion pipeline processes it.
              </p>
              {objectKey && (
                <div className="rounded-lg bg-emerald-100 dark:bg-emerald-900/40 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-500 mb-0.5">
                    S3 object key
                  </p>
                  <p className="text-xs font-mono text-emerald-800 dark:text-emerald-300 break-all">
                    {objectKey}
                  </p>
                </div>
              )}
                      {jobId && (
                        <div className="mt-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 px-3 py-2">
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-500 mb-0.5">
                            Ingestion job
                          </p>
                          <div className="flex items-center gap-2">
                            <p className="text-xs font-mono text-amber-800 dark:text-amber-300 break-all">{jobId}</p>
                            {jobStatusUrl && (
                              <a
                                href={`/rag-api${jobStatusUrl}`}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs text-primary underline ml-2"
                              >
                                View status
                              </a>
                            )}
                            <button
                              onClick={async () => {
                                try {
                                  setJobStatus("checking");
                                  const res = await fetch(`/rag-api${jobStatusUrl}`);
                                  const data = await res.json();
                                  setJobStatus(data.status || JSON.stringify(data));
                                } catch (e) {
                                  setJobStatus("error");
                                }
                              }}
                              className="ml-auto text-xs px-2 py-1 rounded bg-white/80 dark:bg-black/20 border border-border text-muted hover:text-foreground"
                            >
                              Check status
                            </button>
                          </div>
                          {jobStatus && (
                            <p className="text-[11px] text-muted mt-2">Status: {jobStatus}</p>
                          )}
                        </div>
                      )}
              <button
                onClick={clearFile}
                className="text-sm text-emerald-700 dark:text-emerald-400 underline underline-offset-2 hover:text-emerald-900 dark:hover:text-emerald-200 transition-colors"
              >
                Upload another file
              </button>
            </div>
          )}

          {/* Upload button */}
          {file && status !== "success" && (
            <button
              onClick={handleUpload}
              disabled={status === "uploading"}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-primary hover:bg-primary-dark disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
            >
              <Upload className="w-4 h-4" />
              {status === "uploading" ? "Uploading…" : "Upload to S3"}
            </button>
          )}
        </div>
      </main>
    </div>
  );
}
