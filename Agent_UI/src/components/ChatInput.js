"use client";

import { useRef, useEffect } from "react";
import { Send, Loader2 } from "lucide-react";

export default function ChatInput({ value, onChange, onSend, isLoading }) {
  const textareaRef = useRef(null);

  // Auto-focus on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Re-focus after loading completes
  useEffect(() => {
    if (!isLoading) {
      textareaRef.current?.focus();
    }
  }, [isLoading]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "24px";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  useEffect(() => {
    adjustHeight();
  }, [value]);

  return (
    <div className="border-t border-border dark:border-border-dark bg-white dark:bg-[#09090b]">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-3">
        <div className="flex items-end gap-2 bg-surface dark:bg-surface-dark rounded-2xl border border-border dark:border-border-dark px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-primary/30 transition-all">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message..."
            rows={1}
            disabled={isLoading}
            className="flex-1 resize-none bg-transparent text-sm text-foreground placeholder:text-muted outline-none leading-6 disabled:opacity-50"
            style={{ minHeight: "24px", maxHeight: "200px" }}
          />
          <button
            onClick={onSend}
            disabled={!value.trim() || isLoading}
            className="shrink-0 w-8 h-8 rounded-lg bg-primary hover:bg-primary-dark disabled:bg-zinc-200 dark:disabled:bg-zinc-700 disabled:cursor-not-allowed text-white flex items-center justify-center transition-colors"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
        <p className="text-[11px] text-muted text-center mt-2">
          Coding Agent can make mistakes. Verify important information.
        </p>
      </div>
    </div>
  );
}
