#!/usr/bin/env python3
"""
vokk_surface.py — VOKK SurfaceScript for UI panels and browser 3D scenes.

This is a real VOKK-native path for two new artifact classes:

    interface NAME { ... }  -> polished HTML UI preview
    world3d NAME { ... }    -> Three.js browser scene preview

It does NOT mean the whole VOKK runtime is now written in VOKK language.
It means VOKK can generate some UI/3D artifacts through its own surface DSL
instead of only emitting raw HTML/JS.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List


def _tok(line: str) -> List[str]:
    return re.findall(r'"[^"]*"|\S+', line.strip())


def _stripq(s: str) -> str:
    return s.strip().strip('"')


def _extract(source: str, head: str) -> List[Dict[str, str]]:
    out, n = [], len(source)
    for m in re.finditer(r"\b(" + head + r")\s+([A-Za-z_]\w*)\s*\{", source, re.M):
        depth, j = 1, m.end()
        while j < n and depth:
            depth += (source[j] == "{") - (source[j] == "}")
            j += 1
        out.append({"kind": m.group(1), "name": m.group(2), "body": source[m.end():j - 1]})
    return out


def _esc(s: str) -> str:
    return html.escape(s or "")


def _compile_interface(name: str, body: str) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"w": 980, "h": 640, "theme": "dark", "title": name, "subtitle": "", "panels": [], "buttons": []}
    for raw in body.splitlines():
        t = _tok(raw)
        if not t:
            continue
        cmd = t[0].lower()
        if cmd == "size" and len(t) >= 3:
            spec["w"], spec["h"] = int(float(t[1])), int(float(t[2]))
        elif cmd == "theme" and len(t) >= 2:
            spec["theme"] = t[1].lower()
        elif cmd == "title" and len(t) >= 2:
            spec["title"] = _stripq(" ".join(t[1:]))
        elif cmd == "subtitle" and len(t) >= 2:
            spec["subtitle"] = _stripq(" ".join(t[1:]))
        elif cmd == "panel" and len(t) >= 3:
            title = _stripq(t[1]); content = _stripq(" ".join(t[2:]))
            spec["panels"].append({"title": title, "content": content})
        elif cmd == "button" and len(t) >= 2:
            label = _stripq(t[1]); style = t[2].lower() if len(t) >= 3 else "secondary"
            spec["buttons"].append({"label": label, "style": style})
    if not spec["panels"]:
        spec["panels"] = [
            {"title": "Overview", "content": "A calm, useful VOKK-built interface preview."},
            {"title": "Flow", "content": "This surface came from VOKK SurfaceScript rather than raw handwritten HTML."},
        ]
    if not spec["buttons"]:
        spec["buttons"] = [{"label": "Run", "style": "primary"}, {"label": "Pause", "style": "secondary"}]
    dark = spec["theme"] != "light"
    html_out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(spec['title'])}</title>
<style>
:root {{
  --bg:{'#141311' if dark else '#f4efe5'};
  --panel:{'rgba(38,35,31,.78)' if dark else 'rgba(255,250,244,.84)'};
  --ink:{'#f3eee3' if dark else '#2d2a24'};
  --muted:{'#b3a895' if dark else '#7f7362'};
  --line:{'rgba(255,255,255,.12)' if dark else 'rgba(64,52,36,.12)'};
  --accent:{'#f08a5c' if dark else '#bc5f3e'};
}}
*{{box-sizing:border-box}} body{{margin:0;font:15px/1.5 ui-sans-serif,-apple-system,Segoe UI,sans-serif;background:
radial-gradient(1000px 500px at 10% 0%, rgba(240,138,92,.20), transparent 60%),
radial-gradient(800px 460px at 90% 10%, rgba(111,199,173,.14), transparent 58%),
linear-gradient(135deg,var(--bg), {'#221f1a' if dark else '#ebe3d5'});color:var(--ink);min-height:100vh;padding:24px}}
.shell{{max-width:{spec['w']}px;min-height:{spec['h']}px;margin:0 auto;border:1px solid var(--line);border-radius:24px;
background:var(--panel);backdrop-filter:blur(18px) saturate(150%);box-shadow:0 18px 60px rgba(0,0,0,.20), inset 0 1px 0 rgba(255,255,255,.16);overflow:hidden}}
.hero{{padding:28px 28px 20px;border-bottom:1px solid var(--line)}} h1{{margin:0 0 8px;font-size:32px;font-weight:600}} p{{margin:0;color:var(--muted)}}
.buttons{{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}} .btn{{border:1px solid var(--line);border-radius:999px;padding:10px 16px;background:transparent;color:var(--ink);font-weight:600}}
.btn.primary{{background:var(--accent);border-color:transparent;color:white}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;padding:22px}}
.panel{{border:1px solid var(--line);border-radius:18px;padding:16px;background:rgba(255,255,255,.04)}} .panel h3{{margin:0 0 8px;font-size:14px}} .panel p{{margin:0}}
</style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <h1>{_esc(spec['title'])}</h1>
      <p>{_esc(spec['subtitle'])}</p>
      <div class="buttons">
        {''.join(f'<button class="btn {"primary" if b["style"]=="primary" else ""}">{_esc(b["label"])}</button>' for b in spec["buttons"])}
      </div>
    </div>
    <div class="grid">
      {''.join(f'<section class="panel"><h3>{_esc(p["title"])}</h3><p>{_esc(p["content"])}</p></section>' for p in spec["panels"])}
    </div>
  </div>
</body>
</html>"""
    return {"kind": "interface", "name": name, "html": html_out, "source": body}


def _compile_world3d(name: str, body: str) -> Dict[str, Any]:
    spec: Dict[str, Any] = {
        "w": 960,
        "h": 640,
        "background": "#0f1218",
        "horizon": ["#162236", "#0f1218"],
        "camera": [0, 1.6, 6.0],
        "lookat": [0.0, 0.45, 0.0],
        "ambient": ["#ffffff", 0.5],
        "hemi": ["#9bb6ff", "#1e232c", 0.9],
        "directional": [3.8, 5.5, 2.8, "#fff3d6", 2.3],
        "fog": ["#111722", 0.022],
        "orbit": True,
        "shadow": True,
        "sun": [5.5, 7.5, -4.0, 1.6, "#ffe1a8", 1.0],
        "objects": [],
    }

    def mat_from(tokens: List[str]) -> Dict[str, Any]:
        opts: Dict[str, Any] = {"metalness": None, "roughness": None, "emissive": None, "emissiveIntensity": None, "rx": 0.0, "ry": 0.0, "rz": 0.0}
        i = 0
        while i < len(tokens) - 1:
            key = tokens[i].lower()
            val = tokens[i + 1]
            if key in {"metalness", "roughness", "rx", "ry", "rz", "emissiveintensity"}:
                try:
                    opts[key if key != "emissiveintensity" else "emissiveIntensity"] = float(val)
                except ValueError:
                    pass
                i += 2
                continue
            if key == "emissive":
                opts["emissive"] = val
                i += 2
                continue
            i += 1
        return opts

    for raw in body.splitlines():
        t = _tok(raw)
        if not t:
            continue
        cmd = t[0].lower()
        if cmd == "size" and len(t) >= 3:
            spec["w"], spec["h"] = int(float(t[1])), int(float(t[2]))
        elif cmd == "background" and len(t) >= 2:
            spec["background"] = t[1]
        elif cmd == "horizon" and len(t) >= 3:
            spec["horizon"] = [t[1], t[2]]
        elif cmd == "camera" and len(t) >= 4:
            spec["camera"] = [float(t[1]), float(t[2]), float(t[3])]
        elif cmd == "lookat" and len(t) >= 4:
            spec["lookat"] = [float(t[1]), float(t[2]), float(t[3])]
        elif cmd == "ambient" and len(t) >= 3:
            spec["ambient"] = [t[1], float(t[2])]
        elif cmd == "hemilight" and len(t) >= 4:
            spec["hemi"] = [t[1], t[2], float(t[3])]
        elif cmd == "directional" and len(t) >= 6:
            spec["directional"] = [float(t[1]), float(t[2]), float(t[3]), t[4], float(t[5])]
        elif cmd == "sun" and len(t) >= 7:
            spec["sun"] = [float(t[1]), float(t[2]), float(t[3]), float(t[4]), t[5], float(t[6])]
        elif cmd == "fog" and len(t) >= 3:
            spec["fog"] = [t[1], float(t[2])]
        elif cmd == "orbit" and len(t) >= 2:
            spec["orbit"] = t[1].lower() in {"true", "1", "yes", "on"}
        elif cmd == "shadow" and len(t) >= 2:
            spec["shadow"] = t[1].lower() in {"true", "1", "yes", "on"}
        elif cmd == "cube" and len(t) >= 6:
            o = {"type": "box", "x": float(t[1]), "y": float(t[2]), "z": float(t[3]), "size": float(t[4]), "color": t[5]}
            o.update(mat_from(t[6:]))
            spec["objects"].append(o)
        elif cmd == "sphere" and len(t) >= 6:
            o = {"type": "sphere", "x": float(t[1]), "y": float(t[2]), "z": float(t[3]), "size": float(t[4]), "color": t[5]}
            o.update(mat_from(t[6:]))
            spec["objects"].append(o)
        elif cmd == "floor" and len(t) >= 4:
            o = {"type": "floor", "y": float(t[1]), "size": float(t[2]), "color": t[3]}
            o.update(mat_from(t[4:]))
            spec["objects"].append(o)
        elif cmd == "plane" and len(t) >= 7:
            o = {"type": "plane", "x": float(t[1]), "y": float(t[2]), "z": float(t[3]), "w": float(t[4]), "h": float(t[5]), "color": t[6]}
            o.update(mat_from(t[7:]))
            spec["objects"].append(o)
        elif cmd == "torus" and len(t) >= 7:
            o = {"type": "torus", "x": float(t[1]), "y": float(t[2]), "z": float(t[3]), "size": float(t[4]), "tube": float(t[5]), "color": t[6]}
            o.update(mat_from(t[7:]))
            spec["objects"].append(o)
        elif cmd == "cylinder" and len(t) >= 7:
            o = {"type": "cylinder", "x": float(t[1]), "y": float(t[2]), "z": float(t[3]), "radius": float(t[4]), "height": float(t[5]), "color": t[6]}
            o.update(mat_from(t[7:]))
            spec["objects"].append(o)
        elif cmd == "capsule" and len(t) >= 7:
            o = {"type": "capsule", "x": float(t[1]), "y": float(t[2]), "z": float(t[3]), "radius": float(t[4]), "height": float(t[5]), "color": t[6]}
            o.update(mat_from(t[7:]))
            spec["objects"].append(o)
    if not spec["objects"]:
        spec["objects"] = [
            {"type": "floor", "y": -1.2, "size": 18.0, "color": "#171d26", "roughness": 0.95, "metalness": 0.04},
            {"type": "box", "x": -1.35, "y": 0.0, "z": 0.15, "size": 1.35, "color": "#f08a5c", "roughness": 0.42, "metalness": 0.2, "ry": 0.5},
            {"type": "sphere", "x": 1.7, "y": 0.25, "z": -0.45, "size": 0.95, "color": "#6fc7ad", "roughness": 0.18, "metalness": 0.58},
            {"type": "torus", "x": 0.1, "y": 1.4, "z": -1.5, "size": 0.82, "tube": 0.2, "color": "#9ea8ff", "roughness": 0.24, "metalness": 0.62, "rx": 0.8},
        ]
    html_out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(name)}</title>
<style>html,body{{margin:0;height:100%;background:{spec["background"]};overflow:hidden}}
#c{{width:100%;height:100%;display:block}}
.hud{{position:fixed;left:16px;top:14px;color:#f3eee3;font:13px ui-sans-serif,sans-serif;background:rgba(0,0,0,.28);padding:8px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(10px)}}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div class="hud">VOKK world3d · VOKK scene spec + thin browser runtime · orbit {'on' if spec['orbit'] else 'off'}</div>
<script src="https://unpkg.com/three@0.164.1/build/three.min.js"></script>
<script src="https://unpkg.com/three@0.164.1/examples/js/controls/OrbitControls.js"></script>
<script src="/vokk-runtime/world3d.js"></script>
<script>
window.VOKKWorld3D({json.dumps(spec)});
</script>
</body>
</html>"""
    return {"kind": "world3d", "name": name, "html": html_out, "source": body}


def run_surface(source: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for block in _extract(source, "interface|world3d"):
        if block["kind"] == "interface":
            out.append(_compile_interface(block["name"], block["body"]))
        else:
            out.append(_compile_world3d(block["name"], block["body"]))
    return out
