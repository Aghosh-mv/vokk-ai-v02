"use client";

import { useMemo, useState } from "react";

// Native port of the VOKK preview engine. Talks to the guest-OK endpoints
// /api/preview/surface (interface{}/world3d{} -> HTML) and
// /api/preview/runtime (app/route/store/... -> HTML + compiled targets)
// through the same-origin proxy, so no login is required.

const API_BASE = "/api/vokk";

type PreviewMode = "surface" | "runtime";

type SurfaceResult = {
  ok?: boolean;
  error?: string;
  kind?: string;
  name?: string;
  html?: string;
  // runtime-only compiled targets
  python?: string;
  go?: string;
  java?: string;
  vokkscript?: string;
  client_js?: string;
  parsed?: { counts?: Record<string, number> };
};

const SAMPLE_SURFACE = `interface Dashboard {
  title "VOKK Control"
  subtitle "native preview"
  panel "Status" "All systems calm and useful."
  panel "Cortex" "Core / Swift / Scout / Pulse online."
  button "Run" primary
  button "Pause" secondary
}`;

const SAMPLE_RUNTIME = `app TodoApp {
  title "VOKK Todo"
  runtime "python"
}
route ListTodos {
  method "GET"
  path "/todos"
}
store Todos {
  field "title"
  field "done"
}
action AddTodo {
  input "title"
}`;

// world3d previews load /vokk-runtime/world3d.js with an absolute path.
// Inside the iframe srcDoc the base is the Next origin, so rewrite it to
// flow through the proxy and reach the real backend runtime.
function proxify(html: string) {
  return html.replaceAll('"/vokk-runtime/', `"${API_BASE}/vokk-runtime/`);
}

const CODE_KEYS: Array<keyof SurfaceResult> = [
  "python",
  "go",
  "java",
  "vokkscript",
  "client_js",
];

export default function PreviewStudio() {
  const [mode, setMode] = useState<PreviewMode>("surface");
  const [source, setSource] = useState(SAMPLE_SURFACE);
  const [result, setResult] = useState<SurfaceResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<string>("preview");

  const codeTabs = useMemo(() => {
    if (!result) return [] as Array<{ key: string; label: string; code: string }>;
    return CODE_KEYS.filter((k) => typeof result[k] === "string" && result[k]).map(
      (k) => ({ key: k as string, label: k as string, code: result[k] as string }),
    );
  }, [result]);

  async function compile() {
    const src = source.trim();
    if (!src || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/preview/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: src }),
      });
      const json = (await res.json()) as SurfaceResult;
      if (!res.ok || json.error) {
        setResult(null);
        setError(json.error || `compile failed (${res.status})`);
        return;
      }
      setResult(json);
      setTab("preview");
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "compile failed");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: PreviewMode) {
    setMode(next);
    setResult(null);
    setError("");
    setTab("preview");
    setSource(next === "surface" ? SAMPLE_SURFACE : SAMPLE_RUNTIME);
  }

  const counts = result?.parsed?.counts;

  return (
    <section className="chatGrid">
      <div className="chatPanel">
        <div className="panelTitle">preview source</div>

        <div className="composerTop">
          <button
            className={`miniToggle ${mode === "surface" ? "active" : ""}`}
            onClick={() => switchMode("surface")}
          >
            Surface (UI / 3D)
          </button>
          <button
            className={`miniToggle ${mode === "runtime" ? "active" : ""}`}
            onClick={() => switchMode("runtime")}
          >
            Runtime (backend)
          </button>
        </div>

        <textarea
          className="promptBox"
          rows={16}
          value={source}
          onChange={(e) => setSource(e.target.value)}
          spellCheck={false}
          placeholder={
            mode === "surface"
              ? "interface Name { ... } or world3d Name { ... }"
              : "app Name { ... } route Name { ... } store Name { ... }"
          }
        />

        <div className="composerRow">
          <button className="primaryBtn" disabled={busy} onClick={() => void compile()}>
            {busy ? "Compiling..." : "Compile preview"}
          </button>
          <button
            className="ghostBtn"
            onClick={() => switchMode(mode)}
          >
            Reset sample
          </button>
        </div>

        {error ? <div className="noteCard">⚠ {error}</div> : null}
        <div className="statusMeta">
          {mode === "surface"
            ? "interface{} → polished HTML, world3d{} → Three.js scene"
            : "app/route/store/session/action/component → plan + host stubs"}
        </div>
      </div>

      <div className="sidePanels">
        <div className="miniPanel">
          <div className="panelTitle">
            {result
              ? `preview · ${result.kind || mode}${result.name ? ` · ${result.name}` : ""}`
              : "preview output"}
          </div>

          {result ? (
            <>
              <div className="composerTop">
                <button
                  className={`miniToggle ${tab === "preview" ? "active" : ""}`}
                  onClick={() => setTab("preview")}
                >
                  preview
                </button>
                {codeTabs.map((c) => (
                  <button
                    key={c.key}
                    className={`miniToggle ${tab === c.key ? "active" : ""}`}
                    onClick={() => setTab(c.key)}
                  >
                    {c.label}
                  </button>
                ))}
              </div>

              {tab === "preview" ? (
                result.html ? (
                  <iframe
                    className="vokkFrame"
                    sandbox="allow-scripts allow-same-origin"
                    srcDoc={proxify(result.html)}
                    title="VOKK preview"
                  />
                ) : (
                  <div className="emptyState">No HTML preview for this block.</div>
                )
              ) : (
                <pre className="codeBlock">
                  {codeTabs.find((c) => c.key === tab)?.code || ""}
                </pre>
              )}

              {counts ? (
                <div className="statusMeta">
                  {Object.entries(counts)
                    .filter(([, v]) => v)
                    .map(([k, v]) => `${v} ${k}`)
                    .join(" · ") || "parsed"}
                </div>
              ) : null}
            </>
          ) : (
            <div className="emptyState">
              Write VokkScript on the left and compile. Surface blocks render a live
              preview; runtime blocks also emit Python, Go, Java, and VokkScript host
              stubs.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
