"use client";

import { useEffect, useMemo, useState } from "react";
import PreviewStudio from "./PreviewStudio";
import MemoryTools from "./MemoryTools";

const API_BASE = "/api/vokk";
const LIVE_APP_URL =
  process.env.NEXT_PUBLIC_VOKK_LIVE_APP || "http://127.0.0.1:8777";

const modelPresets = [
  "chat",
  "agent",
  "web",
  "scrapegraph",
  "graphrag",
  "agenticrag",
  "selfrag",
  "reasoning",
  "vokkv01",
  "vokkv02",
  "vokkv01_heavy",
  "vokkv02_heavy",
  "vokkv02_lite",
] as const;

const starterPrompts = [
  "Use Canvas to make an AI-generated liquid-glass sunrise over a quiet mountain lake",
  "Use Composer to create an AI-made soft lo-fi melody with glassy bells and warm bass",
  "Use Agent mode to plan a 3-day Munnar trip with web research, costs, and a checklist",
];

type ModelPreset = (typeof modelPresets)[number];
type SideView = "chats" | "artifacts" | "notes" | "projects" | "gems" | "apps";
type MainView = "native" | "preview" | "memory" | "bridge";

type AuthUser = {
  id: number;
  email: string;
  display_name: string;
};

type StatusPayload = {
  live?: boolean;
  gemini?: boolean;
  glm?: boolean;
  serpapi?: boolean;
  model_presets?: string[];
};

type ChatResponse = {
  response?: string;
  error?: string;
  model_preset?: string;
  brain_used?: string;
  routing_reasoning?: string;
  live?: boolean;
  visible_trace?: unknown;
  typo_hints?: Array<{ word: string; suggestion: string }>;
  blocked?: boolean;
};

type Message =
  | { id: string; who: "me"; text: string; ts: number }
  | { id: string; who: "ai"; data: ChatResponse; ts: number };

type Session = {
  id: string;
  title: string;
  msgs: Message[];
  ts: number;
};

type SideItem = {
  id: string;
  title: string;
  body: string;
  ts: number;
};

function greetingFor(name: string) {
  const clean = (name || "friend").trim() || "friend";
  const options = [
    `hello ${clean}`,
    `what is popping, ${clean}?`,
    `yo ${clean}`,
    `welcome ${clean}`,
    `${clean}-san wa ooki desu`,
    `hey ${clean}, what are we building?`,
    `good to see you, ${clean}`,
  ];
  return options[Math.floor(Math.random() * options.length)];
}

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function fmtTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function snippetForSession(session: Session) {
  const last = [...session.msgs].reverse().find((m) => m.who === "me");
  return last && "text" in last ? last.text : "No prompt yet";
}

export default function Home() {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [statusText, setStatusText] = useState("checking local VOKK...");
  const [auth, setAuth] = useState<AuthUser | null>(null);
  const [guestMode, setGuestMode] = useState(false);
  const [authMethod, setAuthMethod] = useState("otp");
  const [loginId, setLoginId] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [authMsg, setAuthMsg] = useState("");
  const [sideView, setSideView] = useState<SideView>("chats");
  const [mainView, setMainView] = useState<MainView>("native");
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window === "undefined") return "dark";
    return localStorage.getItem("vokk-next-theme") === "light" ? "light" : "dark";
  });
  const [showThinking, setShowThinking] = useState(true);
  const [mode, setMode] = useState<"chat" | "think">(() => {
    if (typeof window === "undefined") return "chat";
    return localStorage.getItem("vokk-next-mode") === "think" ? "think" : "chat";
  });
  const [modelPreset, setModelPreset] = useState<ModelPreset>(() => {
    if (typeof window === "undefined") return "chat";
    const saved = localStorage.getItem("vokk-next-model") as ModelPreset | null;
    return saved && modelPresets.includes(saved) ? saved : "chat";
  });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [artifacts, setArtifacts] = useState<SideItem[]>([]);
  const [notes, setNotes] = useState<SideItem[]>([]);
  const [search, setSearch] = useState("");
  const [heroGreeting, setHeroGreeting] = useState("hello friend");

  const currentSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) || null,
    [sessions, activeSessionId],
  );

  const visibleSessions = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((session) =>
      `${session.title} ${session.msgs
        .map((msg) => ("text" in msg ? msg.text : msg.data.response || ""))
        .join(" ")}`
        .toLowerCase()
        .includes(q),
    );
  }, [search, sessions]);

  const visibleSideItems = useMemo(() => {
    const source = sideView === "artifacts" ? artifacts : notes;
    const q = search.trim().toLowerCase();
    if (!q) return source;
    return source.filter((item) =>
      `${item.title} ${item.body}`.toLowerCase().includes(q),
    );
  }, [artifacts, notes, search, sideView]);

  const guestLabel = guestMode && !auth;
  const isLocked = !guestMode && !auth;

  function storagePrefix(email?: string) {
    return email ? `vokk-next-${email}` : "vokk-next-guest";
  }

  function seedGreeting(user?: AuthUser | null) {
    const name = user?.display_name || user?.email?.split("@")[0] || "friend";
    setHeroGreeting(greetingFor(name));
  }

  function saveState(nextSessions: Session[], nextArtifacts: SideItem[], nextNotes: SideItem[], user?: AuthUser | null) {
    const prefix = storagePrefix(user?.email);
    localStorage.setItem(`${prefix}-sessions`, JSON.stringify(nextSessions));
    localStorage.setItem(`${prefix}-artifacts`, JSON.stringify(nextArtifacts));
    localStorage.setItem(`${prefix}-notes`, JSON.stringify(nextNotes));
  }

  function loadState(user?: AuthUser | null, guest = false) {
    if (guest && !user) {
      setSessions([]);
      setArtifacts([]);
      setNotes([]);
      setActiveSessionId(null);
      return;
    }
    const prefix = storagePrefix(user?.email);
    const loadedSessions = JSON.parse(localStorage.getItem(`${prefix}-sessions`) || "[]") as Session[];
    const loadedArtifacts = JSON.parse(localStorage.getItem(`${prefix}-artifacts`) || "[]") as SideItem[];
    const loadedNotes = JSON.parse(localStorage.getItem(`${prefix}-notes`) || "[]") as SideItem[];
    setSessions(loadedSessions);
    setArtifacts(loadedArtifacts);
    setNotes(loadedNotes);
    setActiveSessionId((prev) => prev || loadedSessions[0]?.id || null);
  }

  async function readJsonSafe(res: Response, label: string) {
    const text = await res.text();
    const snippet = text.replace(/\s+/g, " ").trim().slice(0, 180) || "empty response";
    const ctype = (res.headers.get("content-type") || "").toLowerCase();
    if (!ctype.includes("application/json")) {
      throw new Error(`${label} returned non-JSON: ${snippet}`);
    }
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`${label} returned invalid JSON: ${snippet}`);
    }
  }

  async function refreshStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/status`);
      const json = (await readJsonSafe(res, "status")) as StatusPayload;
      setStatus(json);
      setStatusText(json.live ? "local VOKK connected" : "local backend reachable, mock mode");
    } catch (error) {
      setStatusText(
        error instanceof Error ? error.message : "could not reach local VOKK",
      );
    }
  }

  async function checkAuth() {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`);
      const json = (await readJsonSafe(res, "auth check")) as { ok?: boolean; user?: AuthUser };
      if (json.ok && json.user) {
        setAuth(json.user);
        setGuestMode(false);
        seedGreeting(json.user);
        loadState(json.user, false);
        return;
      }
    } catch {
      // keep locked if no auth
    }
    setAuth(null);
    const guest = localStorage.getItem("vokk-next-guest-mode") === "1";
    setGuestMode(guest);
    seedGreeting(null);
    loadState(null, guest);
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const timer = window.setTimeout(() => {
      void refreshStatus();
      void checkAuth();
    }, 0);
    return () => window.clearTimeout(timer);
    // initial sync happens from lazy state above; this effect only kicks off runtime probes
    // and applies the current theme to the document root.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    localStorage.setItem("vokk-next-theme", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("vokk-next-model", modelPreset);
  }, [modelPreset]);

  useEffect(() => {
    localStorage.setItem("vokk-next-mode", mode);
  }, [mode]);

  async function authCall(path: "login" | "register") {
    setAuthMsg("");
    const email = loginId.trim();
    const password = loginPw;
    const display_name = email.split("@")[0] || "VOKK user";
    try {
      const res = await fetch(`${API_BASE}/api/auth/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, display_name, method: authMethod }),
      });
      const json = (await readJsonSafe(res, `auth ${path}`)) as {
        error?: string;
        user?: AuthUser;
        email?: string;
      };
      if (!res.ok || json.error) {
        setAuthMsg(json.error || "auth failed");
        return;
      }
      const user = json.user || {
        id: 0,
        email: json.email || email,
        display_name,
      };
      setAuth(user);
      setGuestMode(false);
      localStorage.removeItem("vokk-next-guest-mode");
      seedGreeting(user);
      loadState(user, false);
    } catch (error) {
      setAuthMsg(error instanceof Error ? error.message : "auth failed");
    }
  }

  async function logout() {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, { method: "POST" });
    } catch {
      // local state reset anyway
    }
    setAuth(null);
    setGuestMode(false);
    localStorage.removeItem("vokk-next-guest-mode");
    setSessions([]);
    setArtifacts([]);
    setNotes([]);
    setActiveSessionId(null);
    seedGreeting(null);
  }

  function continueAsGuest() {
    setGuestMode(true);
    setAuth(null);
    localStorage.setItem("vokk-next-guest-mode", "1");
    setSessions([]);
    setArtifacts([]);
    setNotes([]);
    setActiveSessionId(null);
    seedGreeting(null);
  }

  function ensureSession() {
    if (activeSessionId && currentSession) return currentSession;
    const created: Session = {
      id: uid("chat"),
      title: "New chat",
      msgs: [],
      ts: Date.now(),
    };
    setSessions((prev) => {
      const next = [created, ...prev];
      if (!guestLabel) saveState(next, artifacts, notes, auth);
      return next;
    });
    setActiveSessionId(created.id);
    return created;
  }

  function updateSession(sessionId: string, updater: (session: Session) => Session) {
    setSessions((prev) => {
      const next = prev.map((session) =>
        session.id === sessionId ? updater(session) : session,
      );
      if (!guestLabel) saveState(next, artifacts, notes, auth);
      return next;
    });
  }

  async function sendPrompt() {
    const prompt = draft.trim();
    if (!prompt || sending || isLocked) return;
    const baseSession = ensureSession();
    const sessionId = baseSession.id;
    const userMsg: Message = { id: uid("me"), who: "me", text: prompt, ts: Date.now() };

    updateSession(sessionId, (session) => {
      const title =
        session.msgs.length === 0
          ? prompt.slice(0, 48) || "New chat"
          : session.title;
      return { ...session, title, msgs: [...session.msgs, userMsg], ts: Date.now() };
    });

    setDraft("");
    setSending(true);
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          mode,
          model_preset: modelPreset,
          guest: guestLabel,
        }),
      });
      const json = (await readJsonSafe(res, "chat")) as ChatResponse;
      const aiMsg: Message = {
        id: uid("ai"),
        who: "ai",
        data: !res.ok ? { error: json.error || "chat failed" } : json,
        ts: Date.now(),
      };
      updateSession(sessionId, (session) => ({
        ...session,
        msgs: [...session.msgs, aiMsg],
        ts: Date.now(),
      }));
      if (!json.error && (json.response || json.visible_trace)) {
        setArtifacts((prev) => {
          const next = [
            {
              id: uid("artifact"),
              title: `Reply · ${fmtTime(Date.now())}`,
              body: json.response || "trace-only reply",
              ts: Date.now(),
            },
            ...prev,
          ];
          if (!guestLabel) saveState(sessions, next, notes, auth);
          return next;
        });
      }
    } catch (error) {
      const aiMsg: Message = {
        id: uid("ai"),
        who: "ai",
        data: {
          error: error instanceof Error ? error.message : "chat failed",
        },
        ts: Date.now(),
      };
      updateSession(sessionId, (session) => ({
        ...session,
        msgs: [...session.msgs, aiMsg],
        ts: Date.now(),
      }));
    } finally {
      setSending(false);
    }
  }

  function startNewChat() {
    const created: Session = {
      id: uid("chat"),
      title: "New chat",
      msgs: [],
      ts: Date.now(),
    };
    setSessions((prev) => {
      const next = [created, ...prev];
      if (!guestLabel) saveState(next, artifacts, notes, auth);
      return next;
    });
    setActiveSessionId(created.id);
    setDraft("");
    seedGreeting(auth);
  }

  function deleteSession(sessionId: string) {
    setSessions((prev) => {
      const next = prev.filter((session) => session.id !== sessionId);
      if (!guestLabel) saveState(next, artifacts, notes, auth);
      return next;
    });
    if (activeSessionId === sessionId) {
      setActiveSessionId(null);
      setDraft("");
    }
  }

  function wipeHistory() {
    setSessions([]);
    setArtifacts([]);
    setNotes([]);
    setActiveSessionId(null);
    if (!guestLabel) saveState([], [], [], auth);
  }

  function addNote() {
    const title = `Important note · ${fmtTime(Date.now())}`;
    const body =
      currentSession?.msgs
        .slice(-2)
        .map((msg) => ("text" in msg ? msg.text : msg.data.response || msg.data.error || ""))
        .join("\n\n") || "No current chat context yet.";
    setNotes((prev) => {
      const next = [{ id: uid("note"), title, body, ts: Date.now() }, ...prev];
      if (!guestLabel) saveState(sessions, artifacts, next, auth);
      return next;
    });
    setSideView("notes");
  }

  function addArchivedNote(note: { title: string; body: string }) {
    setNotes((prev) => {
      const next = [
        { id: uid("note"), title: note.title, body: note.body, ts: Date.now() },
        ...prev,
      ];
      if (!guestLabel) saveState(sessions, artifacts, next, auth);
      return next;
    });
    setSideView("notes");
  }

  const sideViewLabel = {
    chats: "Chats",
    artifacts: "Artifacts",
    notes: "Important notes",
    projects: "Projects",
    gems: "Gem library",
    apps: "Apps",
  }[sideView];

  return (
    <>
      <div className={`loginGate ${isLocked ? "show" : ""}`}>
        <div className="loginBox">
          <div className="loginHead">
            <div className="brandMark">V</div>
            <div>
              <h2>Sign in to VOKK</h2>
              <p>Chat history unlocks after login. Guest mode still works without saved history.</p>
            </div>
          </div>
          <div className="authGrid">
            {[
              ["otp", "OTP code", "Email or mobile one-time code"],
              ["gmail", "Continue with Gmail", "Local demo provider flow"],
              ["device", "Use another device", "Approve from a trusted screen"],
              ["recovery", "Recovery email", "Restore account access"],
              ["mobile", "Mobile number", "SMS-style local verification"],
              ["qr", "QR code", "Scan to pair a session"],
            ].map(([value, label, sub]) => (
              <button
                key={value}
                className={`authOpt ${authMethod === value ? "selected" : ""}`}
                onClick={() => setAuthMethod(value)}
              >
                {label}
                <span>{sub}</span>
              </button>
            ))}
          </div>
          <div className="qrRow">
            <div className="qrBlock" />
            <div className="qrCopy">
              Email/password is the real local auth path. The other options are visible entry points
              until real external credentials are wired.
            </div>
          </div>
          <div className="authRow">
            <input
              className="textInput"
              placeholder="email"
              value={loginId}
              onChange={(e) => setLoginId(e.target.value)}
            />
            <input
              className="textInput"
              placeholder="password (8+ chars)"
              type="password"
              value={loginPw}
              onChange={(e) => setLoginPw(e.target.value)}
            />
          </div>
          <div className="authRow">
            <button className="primaryBtn" onClick={() => void authCall("login")}>
              Sign in
            </button>
            <button className="primaryBtn" onClick={() => void authCall("register")}>
              Create account
            </button>
          </div>
          <div className="authRow">
            <button className="ghostBtn" onClick={continueAsGuest}>
              Continue as guest
            </button>
          </div>
          {authMsg ? <div className="authMsg">{authMsg}</div> : null}
        </div>
      </div>

      <main className={`vokk-shell ${theme === "light" ? "lightMode" : ""}`}>
        <aside className="rail">
          <div className="brand">
            <div className="brandMark">V</div>
            <div>
              <div className="brandTitle">VOKK vNext</div>
              <div className="brandSub">Native Next.js migration</div>
            </div>
          </div>

          <button className="newChatBtn" onClick={startNewChat}>
            ✦ New chat
          </button>

          <div className="navGroup">
            {(["chats", "artifacts", "projects", "notes", "gems", "apps"] as SideView[]).map((view) => (
              <button
                key={view}
                className={`navBtn ${sideView === view ? "active" : ""}`}
                onClick={() => setSideView(view)}
              >
                {view}
              </button>
            ))}
          </div>

          <input
            className="searchInput"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chats"
          />

          <div className="sideListWrap">
            <div className="sideListLabel">{sideViewLabel}</div>
            <div className="sideList">
              {sideView === "chats" ? (
                visibleSessions.length ? (
                  visibleSessions.map((session) => (
                    <button
                      key={session.id}
                      className={`sessionCard ${activeSessionId === session.id ? "active" : ""}`}
                      onClick={() => setActiveSessionId(session.id)}
                    >
                      <span>{session.title}</span>
                      <span className="sessionTime">{snippetForSession(session).slice(0, 36)}</span>
                    </button>
                  ))
                ) : (
                  <div className="emptyState">
                    {guestLabel
                      ? "Guest mode works, but session history is temporary."
                      : "No chats yet."}
                  </div>
                )
              ) : sideView === "artifacts" || sideView === "notes" ? (
                visibleSideItems.length ? (
                  visibleSideItems.map((item) => (
                    <div key={item.id} className="sideCard">
                      <strong>{item.title}</strong>
                      <p>{item.body.slice(0, 120)}</p>
                    </div>
                  ))
                ) : (
                  <div className="emptyState">Nothing here yet.</div>
                )
              ) : (
                <div className="emptyState">
                  This section is planned for the native port. The full version is still reachable in
                  the bridge tab.
                </div>
              )}
            </div>
          </div>

          <div className="sideActions">
            <button className="ghostBtn" onClick={addNote}>
              New note
            </button>
            <button className="ghostBtn" onClick={() => setMainView("bridge")}>
              Open bridge
            </button>
            <button className="ghostBtn" onClick={wipeHistory}>
              Delete history
            </button>
            {!guestLabel && auth ? (
              <button className="ghostBtn" onClick={() => void logout()}>
                Sign out
              </button>
            ) : null}
          </div>

          <div className="statusCard">
            <div className={`statusDot ${status?.live ? "on" : ""}`} />
            <div>
              <div className="statusTitle">{statusText}</div>
              <div className="statusMeta">
                {guestLabel ? "guest mode" : auth ? auth.email : "locked"}
              </div>
            </div>
          </div>
        </aside>

        <section className="workspace">
          <header className="topbar">
            <div>
              <div className="eyebrow">Made with AI prompts</div>
              <h1>{heroGreeting}</h1>
            </div>
            <div className="modeRow">
              <button
                className={`modeBtn ${mainView === "native" ? "active" : ""}`}
                onClick={() => setMainView("native")}
              >
                Native shell
              </button>
              <button
                className={`modeBtn ${mainView === "preview" ? "active" : ""}`}
                onClick={() => setMainView("preview")}
              >
                Preview studio
              </button>
              <button
                className={`modeBtn ${mainView === "memory" ? "active" : ""}`}
                onClick={() => setMainView("memory")}
              >
                Memory &amp; archive
              </button>
              <button
                className={`modeBtn ${mainView === "bridge" ? "active" : ""}`}
                onClick={() => setMainView("bridge")}
              >
                Full app bridge
              </button>
              <button className="modeBtn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
                {theme === "dark" ? "Light mode" : "Dark mode"}
              </button>
            </div>
          </header>

          {mainView === "native" ? (
            <>
              <section className="heroPanel">
                <p>
                  This is the native Next shell for VOKK. It now covers login or guest entry,
                  session/sidebar state, chat requests, local notes and artifacts, model selection,
                  and same-origin calls into the current localhost backend. The rest is still being
                  ported and stays reachable in the bridge.
                </p>
                <div className="chipRow">
                  {starterPrompts.map((prompt) => (
                    <button key={prompt} className="chip" onClick={() => setDraft(prompt)}>
                      {prompt}
                    </button>
                  ))}
                </div>
              </section>

              <section className="chatGrid">
                <div className="chatPanel">
                  <div className="panelTitle">chat surface</div>
                  <div className="messageStream">
                    {currentSession?.msgs.length ? (
                      currentSession.msgs.map((msg) =>
                        msg.who === "me" ? (
                          <div key={msg.id} className="bubble me">
                            {msg.text}
                          </div>
                        ) : (
                          <div key={msg.id} className={`bubble ai ${msg.data.blocked ? "blocked" : ""}`}>
                            <div className="bubbleMeta">
                              <span>{msg.data.model_preset || modelPreset}</span>
                              <span>{msg.data.brain_used || "unknown brain"}</span>
                              <span>{msg.data.live === false ? "mock" : "live"}</span>
                            </div>
                            <div className="bubbleText">
                              {msg.data.error || msg.data.response || "No response body"}
                            </div>
                            {showThinking && msg.data.routing_reasoning ? (
                              <div className="bubbleSub">{msg.data.routing_reasoning}</div>
                            ) : null}
                            {showThinking && msg.data.typo_hints?.length ? (
                              <div className="bubbleSub">
                                typos:{" "}
                                {msg.data.typo_hints
                                  .map((hint) => `${hint.word}→${hint.suggestion}`)
                                  .join(", ")}
                              </div>
                            ) : null}
                          </div>
                        ),
                      )
                    ) : (
                      <div className="emptyState">
                        Start a chat here. The native Next shell already sends real requests through the
                        same-origin proxy.
                      </div>
                    )}
                  </div>

                  <div className="composerTop">
                    <button
                      className={`miniToggle ${mode === "chat" ? "active" : ""}`}
                      onClick={() => setMode("chat")}
                    >
                      Chat
                    </button>
                    <button
                      className={`miniToggle ${mode === "think" ? "active" : ""}`}
                      onClick={() => setMode("think")}
                    >
                      Think
                    </button>
                    <label className="thinkingToggle">
                      <input
                        type="checkbox"
                        checked={showThinking}
                        onChange={(e) => setShowThinking(e.target.checked)}
                      />
                      show trace hints
                    </label>
                    <select
                      className="modelSelect"
                      value={modelPreset}
                      onChange={(e) => setModelPreset(e.target.value as ModelPreset)}
                    >
                      {modelPresets.map((preset) => (
                        <option key={preset} value={preset}>
                          {preset}
                        </option>
                      ))}
                    </select>
                  </div>

                  <textarea
                    className="promptBox"
                    rows={5}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="Message VOKK..."
                  />

                  <div className="composerRow">
                    <button className="primaryBtn" disabled={sending || isLocked} onClick={() => void sendPrompt()}>
                      {sending ? "Sending..." : "Send"}
                    </button>
                    <button className="ghostBtn" onClick={() => setDraft(starterPrompts[0])}>
                      Fill sample
                    </button>
                    <button className="ghostBtn" onClick={() => currentSession && deleteSession(currentSession.id)}>
                      Delete chat
                    </button>
                  </div>
                </div>

                <div className="sidePanels">
                  <div className="miniPanel">
                    <div className="panelTitle">migration note</div>
                    <ul className="todoList">
                      <li>Same-origin Next proxy for the local backend is live.</li>
                      <li>Login or guest gate is native in this shell.</li>
                      <li>Session rail, composer, model picker, and note/artifact rails are native.</li>
                      <li>Preview engine, VOKK-DO, and full parity flows are still being ported.</li>
                    </ul>
                  </div>

                  <div className="miniPanel">
                    <div className="panelTitle">current backend</div>
                    <div className="noteCard">
                      Native shell calls:
                      <br />
                      <code>/api/vokk/api/status</code>
                      <br />
                      <code>/api/vokk/api/auth/*</code>
                      <br />
                      <code>/api/vokk/api/chat</code>
                      <br />
                      against the current localhost VOKK host at <code>127.0.0.1:8777</code>.
                    </div>
                  </div>
                </div>
              </section>
            </>
          ) : mainView === "preview" ? (
            <PreviewStudio />
          ) : mainView === "memory" ? (
            <MemoryTools
              loggedIn={!!auth}
              currentSession={currentSession}
              onArchived={addArchivedNote}
            />
          ) : (
            <section className="bridgePanel">
              <div className="bridgeHeader">
                <div>
                  <div className="panelTitle">full live VOKK bridge</div>
                  <div className="statusMeta">{LIVE_APP_URL}</div>
                </div>
                <div className="bridgeActions">
                  <a className="ghostLink" href={LIVE_APP_URL} target="_blank" rel="noreferrer">
                    Open local app
                  </a>
                  <a
                    className="ghostLink"
                    href="https://vokk-project.vercel.app"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open production
                  </a>
                </div>
              </div>
              <iframe className="vokkFrame" src={LIVE_APP_URL} title="Full VOKK app" />
            </section>
          )}
        </section>
      </main>
    </>
  );
}
