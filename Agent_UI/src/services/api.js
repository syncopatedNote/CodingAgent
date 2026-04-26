import axios from "axios";
import { HttpAgent } from "@ag-ui/client";

// API Configuration
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Create axios instance for non-streaming requests (health check, etc.)
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("API Error:", error.response?.data || error.message);
    return Promise.reject(error);
  }
);

/**
 * Check API health status
 * @returns {Promise<{status: string, data?: object, error?: string}>}
 */
export const checkHealth = async () => {
  try {
    const response = await apiClient.get("/api/health", { timeout: 5000 });
    return { status: "healthy", data: response.data };
  } catch (error) {
    return { status: "offline", error: error.message };
  }
};

/**
 * Get the current API base URL
 * @returns {string}
 */
export const getApiBaseUrl = () => API_BASE_URL;

// =====================================================================
// AG-UI Protocol Streaming
// =====================================================================

/**
 * Run a chat turn via the AG-UI protocol endpoint.
 *
 * Creates an HttpAgent, sends the full message history to
 * /api/supervisor/agent, and routes incoming AG-UI events
 * to the provided callback functions.
 *
 * @param {Array<{id:string, role:string, content:string}>} messages
 *   Full conversation history including the latest user message.
 * @param {string} threadId  – Conversation thread identifier.
 * @param {object}  callbacks
 * @param {Function} callbacks.onToken     - (delta: string) called per text chunk
 * @param {Function} callbacks.onMetadata  - (meta: object)  task analysis info
 * @param {Function} callbacks.onStep      - ({step, status}) step lifecycle
 * @param {Function} callbacks.onDone      - ()               run finished normally
 * @param {Function} callbacks.onInterrupt - ({id, reason, payload}) run paused
 * @param {Function} callbacks.onError     - (Error)          error occurred
 * @param {object}   [options]
 * @param {object}   [options.resume]      - {interruptId, payload} to resume
 * @returns {Function} abort – call to cancel the stream
 */
export const runAgentChat = (messages, threadId, callbacks, options = {}) => {
  const {
    onToken,
    onMetadata,
    onStep,
    onDone,
    onInterrupt,
    onError,
  } = callbacks;

  const abortController = new AbortController();

  const agent = new HttpAgent({
    url: `${API_BASE_URL}/api/supervisor/agent`,
  });

  agent.threadId = threadId;
  agent.messages = messages;

  const runId = `run-${Date.now()}`;

  // Build forwardedProps — include resume data when resuming
  const forwardedProps = {};
  if (options.resume) {
    forwardedProps.resume = options.resume;
  }

  // Build an AgentSubscriber to receive events
  const subscriber = {
    onTextMessageContentEvent: ({ event }) => {
      onToken?.(event.delta);
    },
    onCustomEvent: ({ event }) => {
      if (event.name === "task_analysis") {
        onMetadata?.(event.value);
      }
    },
    onStepStartedEvent: ({ event }) => {
      onStep?.({ step: event.stepName, status: "started" });
    },
    onStepFinishedEvent: ({ event }) => {
      onStep?.({ step: event.stepName, status: "finished" });
    },
    onRunFinishedEvent: ({ event }) => {
      if (event.outcome === "interrupt" && event.interrupt) {
        onInterrupt?.({
          id: event.interrupt.id,
          reason: event.interrupt.reason,
          payload: event.interrupt.payload,
        });
      } else {
        onDone?.();
      }
    },
    onRunErrorEvent: ({ event }) => {
      onError?.(new Error(event.message));
    },
    onRunFailed: ({ error }) => {
      onError?.(error);
    },
  };

  agent
    .runAgent(
      { runId, tools: [], context: [], forwardedProps, abortController },
      subscriber,
    )
    .catch((err) => onError?.(err));

  // Return an abort function
  return () => {
    try {
      abortController.abort();
      agent.abortRun?.();
    } catch {
      // ignore abort errors
    }
  };
};

/**
 * Resume a previously interrupted agent run.
 *
 * Convenience wrapper around `runAgentChat` that attaches
 * the resume payload (interruptId + user response) via
 * the AG-UI `forwardedProps` extension point.
 *
 * @param {Array}    messages    – Full conversation history
 * @param {string}   threadId    – Must match the interrupted thread
 * @param {string}   interruptId – The id from the interrupt event
 * @param {object}   payload     – User's response (e.g. {approved: true})
 * @param {object}   callbacks   – Same shape as runAgentChat callbacks
 * @returns {Function} abort
 */
export const resumeAgent = (
  messages,
  threadId,
  interruptId,
  payload,
  callbacks,
) => {
  return runAgentChat(messages, threadId, callbacks, {
    resume: { interruptId, payload },
  });
};

// =====================================================================
// RAG Upload Service
// =====================================================================

/**
 * Request a presigned S3 POST URL from the RAG upload service.
 * The Next.js server proxies /rag-api/* → rag-service, so this
 * works identically in local dev and Docker.
 *
 * @param {string} filename     - Original file name
 * @param {string} contentType  - MIME type (e.g. "application/pdf")
 * @returns {Promise<{url: string, fields: object, object_key: string}>}
 */
export const getPresignedUrl = async (filename, contentType) => {
  const response = await fetch("/rag-api/upload/presigned-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, content_type: contentType }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to get upload URL (${response.status})`);
  }
  return response.json();
};

/**
 * Upload a file directly to S3 using a presigned POST envelope.
 * The file travels browser → S3 directly; the backend is not involved.
 *
 * @param {string}   url        - S3 POST target URL
 * @param {object}   fields     - Presigned form fields (must precede the file)
 * @param {File}     file       - The file object to upload
 * @param {Function} onProgress - (percent: number) progress callback
 * @returns {Promise<void>}
 */
export const uploadFileToS3 = (url, fields, file, onProgress) => {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    // S3 requires all policy fields to appear before the file
    Object.entries(fields).forEach(([k, v]) => formData.append(k, v));
    formData.append("file", file);

    const xhr = new XMLHttpRequest();

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`S3 upload failed with status ${xhr.status}`));
      }
    };

    xhr.onerror = () => reject(new Error("Network error during upload."));

    xhr.open("POST", url);
    xhr.send(formData);
  });
};


/**
 * Notify the backend that an upload completed and request ingestion.
 * @param {string} objectKey
 * @returns {Promise<{job_id:string,status_url:string}>}
 */
export const notifyUploadComplete = async (objectKey) => {
  const response = await fetch(`/rag-api/upload/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_key: objectKey }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to notify upload complete (${response.status})`);
  }
  return response.json();
};

export default {
  checkHealth,
  runAgentChat,
  resumeAgent,
  getApiBaseUrl,
  getPresignedUrl,
  uploadFileToS3,
};
