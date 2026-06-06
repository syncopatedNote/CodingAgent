"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  FileSearch,
  Bot,
  Sparkles,
  BookOpen,
  FileText,
  Table2,
  HelpCircle,
} from "lucide-react";
import ChatMessage, { TypingIndicator } from "@/components/ChatMessage";
import ChatInput from "@/components/ChatInput";
import { checkHealth, runKbSearchAgentChat, getApiBaseUrl } from "@/services/api";

const welcomeCards = [
  { icon: BookOpen,  label: "Summarise uploaded documents", query: "Give me a summary of the documents in the knowledge base" },
  { icon: FileText,  label: "Find specific information",    query: "What does the knowledge base say about authentication?" },
  { icon: Table2,    label: "Look up data from tables",     query: "Show me any tables related to configuration settings" },
  { icon: HelpCircle, label: "Check what's indexed",       query: "What topics are covered in the uploaded documents?" },
];

export default function KnowledgeBasePage() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking");
  const [sessionId] = useState(() => `kb-session-${Date.now()}`);

  const bottomRef = useRef(null);
  const abortStreamRef = useRef(null);

  useEffect(() => {
    const checkApiHealth = async () => {
      const result = await checkHealth();
      setApiStatus(result.status);
    };
    checkApiHealth();
  }, []);

  const scrollToBottom = useCallback(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(scrollToBottom, 50);
    return () => clearTimeout(timer);
  }, [messages, isLoading, scrollToBottom]);

  const sendMessage = async (text) => {
    const userInput = (text || input).trim();
    if (!userInput || isLoading) return;

    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }

    const userMessage = { role: "user", content: userInput };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    const assistantMessage = { role: "assistant", content: "", isStreaming: true };
    setMessages((prev) => [...prev, assistantMessage]);

    const aguiMessages = [
      ...messages.map((m, i) => ({ id: `msg-${i}`, role: m.role, content: m.content })),
      { id: `msg-${messages.length}`, role: "user", content: userInput },
    ];

    abortStreamRef.current = runKbSearchAgentChat(aguiMessages, sessionId, {
      onToken: (delta) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = { ...last, content: last.content + delta };
          }
          return updated;
        });
      },

      onMetadata: () => {},

      onStep: () => {},

      onDone: () => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
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

      onInterrupt: () => {},

      onError: (error) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
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

  const hasMessages = messages.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="shrink-0 flex items-center gap-3 px-4 h-14 border-b border-border dark:border-border-dark bg-white dark:bg-[#09090b]">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-primary rounded-lg flex items-center justify-center">
            <Bot className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-foreground">Cortex</span>
          <span className="text-border dark:text-border-dark mx-1">/</span>
          <span className="text-sm text-muted">Search Knowledge Base</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center gap-1.5">
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
          <Link
            href="/"
            className="flex items-center gap-1.5 text-sm text-muted hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Chat
          </Link>
        </div>
      </header>

      {/* Messages / Welcome */}
      <div className="flex-1 overflow-y-auto">
        {!hasMessages ? (
          <div className="flex flex-col items-center justify-center h-full px-4">
            <div className="max-w-2xl w-full text-center">
              <div className="w-14 h-14 bg-primary/10 rounded-2xl flex items-center justify-center mx-auto mb-6">
                <FileSearch className="w-7 h-7 text-primary" />
              </div>
              <h2 className="text-2xl font-semibold text-foreground mb-2">
                Search Knowledge Base
              </h2>
              <p className="text-sm text-muted mb-8 max-w-md mx-auto">
                Ask questions about your uploaded documents. Answers are grounded
                in the indexed content with source citations.
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
          <div className="py-2">
            {messages.map((msg, i) => (
              <ChatMessage key={i} message={msg} />
            ))}
            {isLoading && messages[messages.length - 1]?.role !== "assistant" && (
              <TypingIndicator />
            )}
            <div ref={bottomRef} className="h-1" />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="shrink-0">
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={() => sendMessage()}
          isLoading={isLoading}
          placeholder="Ask anything about your uploaded documents..."
        />
      </div>
    </div>
  );
}
