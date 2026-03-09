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

export default {
  checkHealth,
  runAgentChat,
  resumeAgent,
  getApiBaseUrl,
};
