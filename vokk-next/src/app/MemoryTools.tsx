"use client";

import { useCallback, useEffect, useState } from "react";

// Native port of the VOKK memory + archive tools. These endpoints require
// a logged-in session (they are not in the backend guest allowlist), so the
// panel asks guests to sign in first.
//
//   GET  /api/memory?q=        -> { memories: [...] }
//   POST /api/memory/add       -> { ok, memory }   ({ scope, title, content })
//   POST /api/context/add      -> { ok, memory, chars } ({ title, content })
//
// "Archive" folds the current chat session into one huge_context memory,
// matching the original sessionArchiveText() serialization.

const API_BASE = "/api/vokk";

type MemoryRow = {
  id: number;
  scope: string;
  title: string;
  content: string;
  source: string;
  created_at: number;
  updated_at: number;
  score?: number;
};

// Loose structural shape of a chat session so this component does not couple
// to the page's internal Session type.
type ArchMessage =
  | { who: "me"; text?: string }
  | { who: "ai"; data?: Record<string, unknown> };

export type ArchSession = {
  id: string;
  title: string;
  msgs: ArchMessage[];
};

type Props = {
  loggedIn: boolean;
  currentSession: ArchSession | null;
  onArchived?: (note: { title: string; body: string }) => void;
};

function serializeSession(c: ArchSession): string {
  const msgs = c.msgs || [];
  const meCount = msgs.filter((m) => m.who === "me").length;
  const aiCount = msgs.filter((m) => m.who === "ai").length;
  const lines: string[] = [
    `Session title: ${c.title || "Untitled"}`,
    `Session id: ${c.id || "unknown"}`,
    `Archived at: ${new Date().toISOString()}`,
    `Message count: ${msgs.length}`,
    `Turns: user ${meCount} · ai ${aiCount}`,
    "",
    "[Session detail]",
  ];
  msgs.forEach((m, i) => {
    lines.push(`Turn ${i + 1} · ${m.who || "unknown"}`);
    if (m.who === "me") {
      lines.push(m.text || "");
    } else {
      const d = (m.data || {}) as Record<string, unknown>;
      const meta = [
        d.brain_used ? `brain=${d.brain_used}` : "",
        d.model_preset ? `model=${d.model_preset}` : "",
        d.routing_reasoning ? `route=${d.routing_reasoning}` : "",
        d.audit_hash ? `audit=${d.audit_hash}` : "",
        d.live === false ? "live=mock" : "live=live",
        d.verified ? "verified=true" : "",
      ]
        .filter(Boolean)
        .join(" | ");
      if (meta) lines.push(`Meta: ${meta}`);
      if (d.response) lines.push(`Response:\n${d.response}`);
      if (d.thinking) lines.push(`Thinking:\n${d.thinking}`);
      if (d.vokk_source) lines.push(`Generated VOKK source:\n${d.vokk_source}`);
      if (d.blocked) lines.push("Blocked payload: true");
    }
    lines.push("");
  });
  return lines.join("\n");
}

export default function MemoryTools({ loggedIn, currentSession, onArchived }: Props) {
  const [query, setQuery] = useState("");
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");

  // add-memory form
  const [scope, setScope] = useState("general");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [hugeContext, setHugeContext] = useState(false);

  const search = useCallback(async () => {
    if (!loggedIn) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/memory?q=${encodeURIComponent(query)}`);
      const json = (await res.json()) as { memories?: MemoryRow[]; error?: string };
      if (!res.ok || json.error) {
        setStatus(json.error || "search failed");
        return;
      }
      setMemories(json.memories || []);
      setStatus(`${json.memories?.length || 0} memories`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "search failed");
    } finally {
      setLoading(false);
    }
  }, [loggedIn, query]);

  useEffect(() => {
    if (loggedIn) void search();
    // run once on login; later searches are explicit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loggedIn]);

  async function saveMemory() {
    const body = content.trim();
    if (!body) {
      setStatus("memory content required");
      return;
    }
    const path = hugeContext ? "/api/context/add" : "/api/memory/add";
    const payload = hugeContext
      ? { title: title.trim() || "Huge context", content: body }
      : { scope: scope.trim() || "general", title: title.trim() || "Memory", content: body };
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = (await res.json()) as { ok?: boolean; error?: string; chars?: number };
      if (!res.ok || json.error) {
        setStatus(json.error || "save failed");
        return;
      }
      setStatus(hugeContext ? `stored ${json.chars ?? body.length} chars` : "memory saved");
      setTitle("");
      setContent("");
      void search();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "save failed");
    }
  }

  async function archiveSession() {
    if (!currentSession || !currentSession.msgs?.length) {
      setStatus("no active chat to archive");
      return;
    }
    const archiveTitle = `${(currentSession.title || "Session archive").trim()} · archive`;
    const archiveContent = serializeSession(currentSession);
    try {
      const res = await fetch(`${API_BASE}/api/context/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: archiveTitle, content: archiveContent }),
      });
      const json = (await res.json()) as { ok?: boolean; error?: string; chars?: number };
      if (!res.ok || json.error) {
        setStatus(json.error || "archive failed");
        return;
      }
      const chars = json.chars ?? archiveContent.length;
      setStatus(`archived ${chars} chars into huge context`);
      onArchived?.({
        title: archiveTitle,
        body: `Archived current session into huge context. ${chars} chars stored.`,
      });
      void search();
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "archive failed");
    }
  }

  if (!loggedIn) {
    return (
      <section className="heroPanel">
        <div className="panelTitle">memory &amp; archive</div>
        <p>
          Memory search, saved memories, huge-context storage, and session archiving
          run against your account. Sign in (close the guest banner and use the login
          gate) to use these tools. Guest chats stay local and are not archived.
        </p>
      </section>
    );
  }

  return (
    <section className="chatGrid">
      <div className="chatPanel">
        <div className="panelTitle">memory search</div>
        <div className="composerTop">
          <input
            className="searchInput"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void search();
            }}
            placeholder="Search your memories"
          />
          <button className="primaryBtn" disabled={loading} onClick={() => void search()}>
            {loading ? "Searching..." : "Search"}
          </button>
          <button
            className="ghostBtn"
            disabled={!currentSession?.msgs?.length}
            onClick={() => void archiveSession()}
          >
            Archive current chat
          </button>
        </div>

        <div className="messageStream">
          {memories.length ? (
            memories.map((m) => (
              <div key={m.id} className="sideCard">
                <strong>{m.title}</strong>
                <div className="statusMeta">
                  {m.scope} · {m.source}
                  {typeof m.score === "number" && m.score > 0 ? ` · match ${m.score}` : ""}
                </div>
                <p>{m.content.slice(0, 280)}</p>
              </div>
            ))
          ) : (
            <div className="emptyState">No memories yet. Save one on the right.</div>
          )}
        </div>
        {status ? <div className="statusMeta">{status}</div> : null}
      </div>

      <div className="sidePanels">
        <div className="miniPanel">
          <div className="panelTitle">save memory</div>
          <label className="thinkingToggle">
            <input
              type="checkbox"
              checked={hugeContext}
              onChange={(e) => setHugeContext(e.target.checked)}
            />
            store as huge context
          </label>
          {!hugeContext ? (
            <input
              className="textInput"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              placeholder="scope (e.g. general, project)"
            />
          ) : null}
          <input
            className="textInput"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="title"
          />
          <textarea
            className="promptBox"
            rows={6}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={hugeContext ? "Paste a large reference body..." : "What should VOKK remember?"}
          />
          <div className="composerRow">
            <button className="primaryBtn" onClick={() => void saveMemory()}>
              {hugeContext ? "Store context" : "Save memory"}
            </button>
          </div>
          <div className="statusMeta">
            Memories feed retrieval on future chats. Huge context stores large bodies
            for reuse.
          </div>
        </div>
      </div>
    </section>
  );
}
