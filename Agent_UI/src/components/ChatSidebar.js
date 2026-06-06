"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Plus,
  Upload,
  MessageSquare,
  Search,
  Code2,
  Zap,
  Database,
  GitBranch,
  Sparkles,
  ChevronLeft,
  ExternalLink,
  Trash2,
  Bot,
} from "lucide-react";

export default function ChatSidebar({ isOpen, onClose, onNewChat, onSelectExample, apiStatus }) {
  const examples = [
    { icon: Search, label: "Search API docs", query: "Search for API authentication documentation" },
    { icon: MessageSquare, label: "What can you do?", query: "What can you help me with?" },
    { icon: Code2, label: "Generate code", query: "Generate code for CBP-8446" },
    { icon: Database, label: "Find a ticket", query: "Show me details for PROJ-123" },
    { icon: Search, label: "Find bugs", query: "Search for recent bugs in production" },
    { icon: Code2, label: "Confluence search", query: "Find confluence pages about deployment" },
  ];

  const capabilities = [
    { icon: Search, title: "Intelligent Search", desc: "Confluence, Jira, vector RAG" },
    { icon: Code2, title: "Code Generation", desc: "From Jira tickets + GitLab" },
    { icon: Zap, title: "Smart Routing", desc: "Automatic task classification" },
    { icon: Database, title: "Enterprise RAG", desc: "Multi-modal document processing" },
    { icon: GitBranch, title: "MCP Integrations", desc: "Confluence, Jira, GitLab" },
    { icon: Sparkles, title: "Multi-LLM", desc: "Ollama, OpenAI, AWS Bedrock" },
  ];

  return (
    <>
      {/* Overlay for mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`
          fixed top-0 left-0 bottom-0 z-50 w-72
          bg-sidebar dark:bg-sidebar-dark
          border-r border-border dark:border-border-dark
          flex flex-col
          transition-transform duration-300 ease-in-out
          lg:relative lg:translate-x-0
          ${isOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border dark:border-border-dark">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-sm text-foreground">Cortex</span>
          </div>
          <button
            onClick={onClose}
            className="lg:hidden p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-zinc-800 text-muted transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>

        {/* New Chat */}
        <div className="p-3 pb-1 space-y-2">
          <button
            onClick={onNewChat}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg border border-border dark:border-border-dark hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors text-sm font-medium text-foreground"
          >
            <Plus className="w-4 h-4" />
            New Chat
          </button>
          <Link
            href="/upload"
            onClick={onClose}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg border border-dashed border-border dark:border-border-dark hover:bg-primary/5 hover:border-primary/40 dark:hover:bg-primary/10 transition-colors text-sm font-medium text-muted hover:text-foreground"
          >
            <Upload className="w-4 h-4" />
            Upload Documents for RAG
          </Link>
          <Link
            href="/knowledge-base"
            onClick={onClose}
            className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg border border-dashed border-border dark:border-border-dark hover:bg-primary/5 hover:border-primary/40 dark:hover:bg-primary/10 transition-colors text-sm font-medium text-muted hover:text-foreground"
          >
            <Search className="w-4 h-4" />
            Search Knowledge Base
          </Link>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          {/* Try These */}
          <div className="mb-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted px-2 mb-2">
              Try these
            </p>
            <div className="space-y-0.5">
              {examples.map((ex, i) => (
                <button
                  key={i}
                  onClick={() => onSelectExample(ex.query)}
                  className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-sm text-zinc-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800 hover:text-foreground transition-colors group"
                >
                  <ex.icon className="w-3.5 h-3.5 shrink-0 text-muted group-hover:text-primary transition-colors" />
                  <span className="truncate">{ex.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Capabilities */}
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted px-2 mb-2">
              Capabilities
            </p>
            <div className="space-y-0.5">
              {capabilities.map((cap, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2.5 px-2.5 py-2 rounded-lg text-sm"
                >
                  <cap.icon className="w-3.5 h-3.5 shrink-0 text-primary mt-0.5" />
                  <div className="min-w-0">
                    <p className="font-medium text-foreground text-xs">{cap.title}</p>
                    <p className="text-[11px] text-muted truncate">{cap.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-border dark:border-border-dark space-y-2">
          <div className="flex items-center gap-2 px-2">
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                apiStatus === "healthy"
                  ? "bg-green-500"
                  : apiStatus === "offline"
                  ? "bg-red-500"
                  : "bg-yellow-500 animate-pulse"
              }`}
            />
            <span className="text-[11px] text-muted">
              {apiStatus === "healthy" ? "API Connected" : apiStatus === "offline" ? "API Offline" : "Checking..."}
            </span>
          </div>
          <div className="flex gap-1.5">
            <a
              href="http://localhost:8000/api/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md text-[11px] text-muted hover:text-foreground hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors"
            >
              Swagger <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        </div>
      </aside>
    </>
  );
}
