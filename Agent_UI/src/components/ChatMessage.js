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

/**
 * Animated wired-brain SVG — shown while waiting for the first response token.
 *
 * The two lobes each contain a rectangular circuit loop with corner nodes.
 * CSS animations drive a traveling "signal" dash along each loop, plus
 * individual node-glow pulses.
 */
function WiredBrainLoader({ width = 52 }) {
  const height = Math.round(width * 0.719); // 52 → 37px; preserves 64:46 ratio
  return (
    <svg
      viewBox="0 0 64 46"
      width={width}
      height={height}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="wired-brain text-primary"
      aria-label="Processing"
    >
      {/* ── Brain silhouette ── */}
      {/* Left lobe */}
      <path
        d="M32 5C27 1 15 0 9 8C3 15 3 23 6 29C9 35 15 40 20 43C23 45 27 46 32 46"
        stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
      />
      {/* Right lobe */}
      <path
        d="M32 5C37 1 49 0 55 8C61 15 61 23 58 29C55 35 49 40 44 43C41 45 37 46 32 46"
        stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
      />
      {/* Center fissure */}
      <path
        d="M32 5C31 13 31 21 32 31C33 39 32 43 32 46"
        stroke="currentColor" strokeWidth="0.9" strokeDasharray="2 4" opacity="0.4"
      />

      {/* ── Left hemisphere circuit ── */}
      {/* Top rail with bump up */}
      <path d="M8 19H13V15H20V19H29" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" opacity="0.5"/>
      {/* Bottom rail with bump down */}
      <path d="M8 33H13V37H20V33H29" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" opacity="0.5"/>
      {/* Vertical connectors */}
      <line x1="13" y1="19" x2="13" y2="33" stroke="currentColor" strokeWidth="0.9" opacity="0.35"/>
      <line x1="20" y1="19" x2="20" y2="33" stroke="currentColor" strokeWidth="0.9" opacity="0.35"/>

      {/* ── Right hemisphere circuit ── */}
      {/* Top rail with bump up */}
      <path d="M56 19H51V15H44V19H35" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" opacity="0.5"/>
      {/* Bottom rail with bump down */}
      <path d="M56 33H51V37H44V33H35" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" opacity="0.5"/>
      {/* Vertical connectors */}
      <line x1="51" y1="19" x2="51" y2="33" stroke="currentColor" strokeWidth="0.9" opacity="0.35"/>
      <line x1="44" y1="19" x2="44" y2="33" stroke="currentColor" strokeWidth="0.9" opacity="0.35"/>

      {/*
        ── Animated signal traces ──
        Each trace follows the same rectangle as the static circuit lines.
        strokeDasharray="9 63" + path length 72px → exactly one 9px dash
        visible at all times, circling the loop continuously.
      */}
      <path
        d="M8 19H13V15H20V19H29V33H20V37H13V33H8"
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        strokeDasharray="9 63"
        className="brain-sig-l"
      />
      <path
        d="M56 19H51V15H44V19H35V33H44V37H51V33H56"
        stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        strokeDasharray="9 63"
        className="brain-sig-r"
      />

      {/* ── Corner nodes — left lobe ── */}
      {[[13,15],[20,15],[13,19],[20,19],[13,33],[20,33],[13,37],[20,37]].map(([cx,cy],i) => (
        <circle key={i} cx={cx} cy={cy} r="2.3" fill="currentColor" className={`brain-node n${i % 4}`}/>
      ))}
      {/* ── Corner nodes — right lobe ── */}
      {[[51,15],[44,15],[51,19],[44,19],[51,33],[44,33],[51,37],[44,37]].map(([cx,cy],i) => (
        <circle key={i+8} cx={cx} cy={cy} r="2.3" fill="currentColor" className={`brain-node n${(i+2) % 4}`}/>
      ))}

      {/* ── Cord at bottom ── */}
      <path d="M29 46C30 47 31 48 32 49C33 48 34 47 35 46" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.5"/>
    </svg>
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

  // Phase 1: streaming started but no content yet → show the animated brain
  const showBrainLoader = !isUser && message.isStreaming && !message.content;

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

            {showBrainLoader ? (
              /* Waiting for first token — animated brain replaces the static cursor */
              <div className="mt-1">
                <WiredBrainLoader />
              </div>
            ) : (
              <div className="msg-content text-sm leading-relaxed text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap break-words">
                {message.content}
                {message.isStreaming && (
                  <span className="inline-block w-[3px] h-[1.1em] bg-zinc-500 dark:bg-zinc-400 ml-0.5 align-text-bottom animate-blink" />
                )}
              </div>
            )}

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
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-semibold text-foreground">Cortex</span>
            </div>
            <WiredBrainLoader />
          </div>
        </div>
      </div>
    </div>
  );
}
