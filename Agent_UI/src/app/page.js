"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Menu,
  Search,
  Code2,
  MessageSquare,
  Database,
  Bot,
  Sparkles,
} from "lucide-react";
import ChatSidebar from "@/components/ChatSidebar";
import ChatMessage, { TypingIndicator } from "@/components/ChatMessage";
import ChatInput from "@/components/ChatInput";
import { checkHealth, runAgentChat, resumeAgent, getApiBaseUrl } from "@/services/api";

const welcomeCards = [
  { icon: Search, label: "Search documentation", query: "Search for API authentication documentation" },
  { icon: Code2, label: "Generate code from ticket", query: "Generate code for CBP-8446" },
  { icon: MessageSquare, label: "What can you help with?", query: "What can you help me with?" },
  { icon: Database, label: "Look up a Jira ticket", query: "Show me details for PROJ-123" },
];

export default function Home() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking");
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const [pendingInterrupt, setPendingInterrupt] = useState(null);

  const scrollAreaRef = useRef(null);
  const bottomRef = useRef(null);

  // Health check
  useEffect(() => {
    const checkApiHealth = async () => {
      const result = await checkHealth();
      setApiStatus(result.status);
    };
    checkApiHealth();
  }, []);

  // Scroll to bottom whenever messages change or loading state changes
  const scrollToBottom = useCallback(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, []);

  useEffect(() => {
    // Use a small delay to ensure DOM has rendered the new message
    const timer = setTimeout(scrollToBottom, 50);
    return () => clearTimeout(timer);
  }, [messages, isLoading, scrollToBottom]);

  // Reference to hold the abort function for the current stream
  const abortStreamRef = useRef(null);

  const sendMessage = async (text) => {
    const userInput = (text || input).trim();
    if (!userInput || isLoading) return;

    // Cancel any ongoing stream
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }

    const userMessage = { role: "user", content: userInput };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    // Create a placeholder assistant message for streaming
    const assistantMessage = {
      role: "assistant",
      content: "",
      isStreaming: true,
      taskAnalysis: null,
    };
    setMessages((prev) => [...prev, assistantMessage]);

    // Build full AG-UI message array (history + new message)
    const aguiMessages = [
      ...messages.map((m, i) => ({
        id: `msg-${i}`,
        role: m.role,
        content: m.content,
      })),
      { id: `msg-${messages.length}`, role: "user", content: userInput },
    ];

    abortStreamRef.current = runAgentChat(aguiMessages, sessionId, {
      // AG-UI TEXT_MESSAGE_CONTENT → append delta
      onToken: (delta) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: last.content + delta,
            };
          }
          return updated;
        });
      },

      // AG-UI CUSTOM(task_analysis) → attach metadata
      onMetadata: (metadata) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              taskAnalysis: metadata,
            };
          }
          return updated;
        });
      },

      // AG-UI STEP events (optional future use)
      onStep: () => {},

      // AG-UI RUN_FINISHED → finalize
      onDone: () => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: last.content || "No response was generated.",
              isStreaming: false,
            };
          }
          return updated;
        });
        setIsLoading(false);
        abortStreamRef.current = null;
      },

      // AG-UI INTERRUPT → agent paused, awaiting user input
      onInterrupt: (interrupt) => {
        setPendingInterrupt(interrupt);
        const question = interrupt?.payload?.question || `Agent needs input (${interrupt.reason})`;
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: last.content || question,
              isStreaming: false,
              interrupt,
            };
          }
          return updated;
        });
        setIsLoading(false);
        abortStreamRef.current = null;
      },

      // AG-UI RUN_ERROR → show error
      onError: (error) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: last.content || error.message || "An error occurred.",
              isStreaming: false,
            };
          }
          return updated;
        });
        setIsLoading(false);
        abortStreamRef.current = null;
      },
    });
  };

  /**
   * Resume an interrupted agent run.
   * @param {boolean} approved - Whether the user approved the action
   * @param {object}  [extra]  - Additional payload to send with the resume
   */
  const handleResumeInterrupt = (approved, extra = {}) => {
    if (!pendingInterrupt) return;

    const interruptId = pendingInterrupt.id;
    const answer = extra.answer || "";

    // Add the user's answer as a visible message and clear interrupt from the message
    if (answer) {
      setMessages((prev) => {
        const updated = prev.map((m) =>
          m.interrupt ? { ...m, interrupt: undefined } : m
        );
        return [...updated, { role: "user", content: answer }];
      });
    } else {
      setMessages((prev) =>
        prev.map((m) => (m.interrupt ? { ...m, interrupt: undefined } : m))
      );
    }

    setPendingInterrupt(null);
    setIsLoading(true);

    // Add a placeholder assistant message for the resumed response
    const assistantMessage = {
      role: "assistant",
      content: "",
      isStreaming: true,
      taskAnalysis: null,
    };
    setMessages((prev) => [...prev, assistantMessage]);

    const aguiMessages = messages.map((m, i) => ({
      id: `msg-${i}`,
      role: m.role,
      content: m.content,
    }));

    abortStreamRef.current = resumeAgent(
      aguiMessages,
      sessionId,
      interruptId,
      { approved, ...extra },
      {
        onToken: (delta) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + delta,
              };
            }
            return updated;
          });
        },
        onMetadata: (metadata) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                taskAnalysis: metadata,
              };
            }
            return updated;
          });
        },
        onStep: () => {},
        onDone: () => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content || "Action completed.",
                isStreaming: false,
              };
            }
            return updated;
          });
          setIsLoading(false);
          abortStreamRef.current = null;
        },
        onInterrupt: (interrupt) => {
          // Nested interrupt (rare but possible)
          setPendingInterrupt(interrupt);
          const question = interrupt?.payload?.question || `Agent needs input (${interrupt.reason})`;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content || question,
                isStreaming: false,
                interrupt,
              };
            }
            return updated;
          });
          setIsLoading(false);
          abortStreamRef.current = null;
        },
        onError: (error) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content || error.message || "An error occurred.",
                isStreaming: false,
              };
            }
            return updated;
          });
          setIsLoading(false);
          abortStreamRef.current = null;
        },
      },
    );
  };

  const handleNewChat = () => {
    setMessages([]);
    setPendingInterrupt(null);
    setSidebarOpen(false);
  };

  const handleSelectExample = (query) => {
    setSidebarOpen(false);
    sendMessage(query);
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <ChatSidebar
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNewChat={handleNewChat}
        onSelectExample={handleSelectExample}
        apiStatus={apiStatus}
      />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {/* Top Bar */}
        <header className="shrink-0 flex items-center gap-3 px-4 h-14 border-b border-border dark:border-border-dark bg-white dark:bg-[#09090b]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 -ml-2 rounded-lg hover:bg-gray-100 dark:hover:bg-zinc-800 text-muted hover:text-foreground transition-colors lg:hidden"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-primary" />
            <h1 className="text-sm font-semibold text-foreground">Cortex</h1>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                apiStatus === "healthy"
                  ? "bg-green-500"
                  : apiStatus === "offline"
                  ? "bg-red-500"
                  : "bg-yellow-500 animate-pulse"
              }`}
            />
            <span className="text-[11px] text-muted hidden sm:inline">
              {apiStatus === "healthy" ? "Connected" : apiStatus === "offline" ? "Offline" : "Checking..."}
            </span>
          </div>
        </header>

        {/* Messages / Welcome — this is the scrollable area */}
        <div ref={scrollAreaRef} className="flex-1 overflow-y-auto">
          {!hasMessages ? (
            /* Welcome Screen */
            <div className="flex flex-col items-center justify-center h-full px-4">
              <div className="max-w-2xl w-full text-center">
                <div className="w-14 h-14 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-6">
                  <Sparkles className="w-7 h-7 text-primary" />
                </div>
                <h2 className="text-2xl font-semibold text-foreground mb-2">
                  Hi, I&apos;m Cortex.
                  How can I help you?
                </h2>
                <p className="text-sm text-muted mb-8 max-w-md mx-auto">
                  I can search documentation, generate code from Jira tickets, and answer questions about your enterprise systems.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-lg mx-auto">
                  {welcomeCards.map((card, i) => (
                    <button
                      key={i}
                      onClick={() => sendMessage(card.query)}
                      className="flex items-center gap-3 px-4 py-3.5 rounded-xl border border-border dark:border-border-dark hover:border-primary/40 hover:bg-primary/[0.03] dark:hover:bg-primary/[0.05] text-left transition-all group"
                    >
                      <card.icon className="w-4 h-4 text-muted group-hover:text-primary transition-colors shrink-0" />
                      <span className="text-sm text-zinc-600 dark:text-zinc-400 group-hover:text-foreground transition-colors">
                        {card.label}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            /* Message List */
            <div className="py-2">
              {messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} />
              ))}
              {isLoading && messages[messages.length - 1]?.role !== "assistant" && <TypingIndicator />}
              <div ref={bottomRef} className="h-1" />
            </div>
          )}
        </div>

        {/* Input — always pinned at bottom */}
        <div className="shrink-0">
          {pendingInterrupt ? (
            <ChatInput
              value={input}
              onChange={setInput}
              onSend={() => {
                const answer = input.trim();
                if (answer) {
                  setInput("");
                  handleResumeInterrupt(true, { answer });
                }
              }}
              isLoading={isLoading}
              placeholder="Type your answer..."
            />
          ) : (
            <ChatInput
              value={input}
              onChange={setInput}
              onSend={() => sendMessage()}
              isLoading={isLoading}
            />
          )}
        </div>
      </div>
    </div>
  );
}
