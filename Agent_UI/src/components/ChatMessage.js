"use client";

import { useState } from "react";
import { Bot, User, Copy, Check } from "lucide-react";

function TaskBadge({ taskType, confidence }) {
  const config = {
    search_operation: { label: "Search", bg: "bg-blue-50 dark:bg-blue-500/10", text: "text-blue-600 dark:text-blue-400" },
    code_generation: { label: "Code Gen", bg: "bg-emerald-50 dark:bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400" },
    general_chat: { label: "Chat", bg: "bg-violet-50 dark:bg-violet-500/10", text: "text-violet-600 dark:text-violet-400" },
  };
  const c = config[taskType] || config.general_chat;
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full ${c.bg} ${c.text}`}>
      {c.label}
      {confidence > 0 && (
        <span className="opacity-60">{Math.round(confidence * 100)}%</span>
      )}
    </span>
  );
}

export default function ChatMessage({ message }) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`animate-message ${isUser ? "" : ""}`}>
      <div
        className={`max-w-3xl mx-auto px-4 sm:px-6 py-5 ${
          isUser ? "" : "bg-surface dark:bg-surface-dark"
        }`}
      >
        <div className="flex gap-4">
          {/* Avatar */}
          <div className="shrink-0">
            {isUser ? (
              <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center">
                <User className="w-3.5 h-3.5 text-white" />
              </div>
            ) : (
              <div className="w-7 h-7 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center">
                <Bot className="w-3.5 h-3.5 text-primary" />
              </div>
            )}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-semibold text-foreground">
                {isUser ? "You" : "Cortex"}
              </span>
              {!isUser && message.taskAnalysis && (
                <TaskBadge
                  taskType={message.taskAnalysis.task_type}
                  confidence={message.taskAnalysis.confidence}
                />
              )}
            </div>
            <div className="msg-content text-sm leading-relaxed text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words">
              {message.content}
              {message.isStreaming && (
                <span className="inline-block w-[3px] h-[1.1em] bg-zinc-500 dark:bg-zinc-400 ml-0.5 align-text-bottom animate-blink" />
              )}
            </div>
            {!isUser && !message.isStreaming && (
              <div className="mt-2">
                <button
                  onClick={handleCopy}
                  className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-foreground transition-colors"
                >
                  {copied ? (
                    <><Check className="w-3 h-3" /> Copied</>
                  ) : (
                    <><Copy className="w-3 h-3" /> Copy</>
                  )}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="animate-message">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-5 bg-surface dark:bg-surface-dark">
        <div className="flex gap-4">
          <div className="w-7 h-7 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center shrink-0">
            <Bot className="w-3.5 h-3.5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm font-semibold text-foreground">
                Cortex
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-zinc-600 dark:text-zinc-400 animate-pulse">Thinking...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
