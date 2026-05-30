#!/usr/bin/env python3
"""
vokk_lang.py — the VokkScript creative interpreter with a real IR layer.

The signature VOKK idea: images & music are PROGRAMMED, not prompted. But the
translation is NOT direct — it passes through a neutral intermediate
representation ("Vokk IR", the vokk-understandable form), and it works in BOTH
directions:

    code (VokkScript / other)  ──parse──►  Vokk IR  ──render──►  image / music
    image / music              ──lift───►  Vokk IR  ──emit────►  VokkScript

So the IR is the hub. The interpreter can read code written in VokkScript (its
native creative syntax), translate to IR, and render. It can also take an
existing artifact (SVG / note-score), lift it back to IR, and emit VokkScript —
making the pipeline reversible and reproducible. No image/audio API anywhere.

Public API:
    run_vokk(source)        -> [artifact, ...]    forward: code -> IR -> render
    to_ir(source)           -> [VokkIR, ...]      code -> IR
    render_ir(ir)           -> artifact           IR -> image/music
    svg_to_ir(svg, name)    -> VokkIR             reverse: SVG  -> IR
    score_to_ir(score, ...) -> VokkIR             reverse: notes -> IR
    emit_vokkscript(ir)     -> str                IR -> VokkScript code
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# ── Note <-> frequency (equal temperament, A4 = 440 Hz) ────────────────────
_NOTE_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SEMITONE_NOTE = {0: "C", 1: "C#", 2: "D", 3: "D#", 4: "E", 5: "F",
                  6: "F#", 7: "G", 8: "G#", 9: "A", 10: "A#", 11: "B"}


def note_to_freq(note: str) -> Optional[float]:
    """C4 -> 261.63 Hz. '_'/'rest' -> None (silence)."""
    note = note.strip()
    if note in ("_", "rest", "-"):
        return None
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", note)
    if not m:
        return None
    letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3))
    semis = _NOTE_SEMITONE[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)
    midi = semis + (octave + 1) * 12
    return round(440.0 * (2 ** ((midi - 69) / 12)), 3)


def freq_to_note(freq: Optional[float]) -> str:
    """261.63 -> 'C4'. None -> '_'."""
    if not freq:
        return "_"
    import math
    midi = round(69 + 12 * math.log2(freq / 440.0))
    name = _SEMITONE_NOTE[midi % 12]
    octave = midi // 12 - 1
    return f"{name}{octave}"


# ═══════════════════════════════════════════════════════════════════════════
# THE IR — the vokk-understandable hub form. Everything routes through this.
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class VokkIR:
    kind: str                                  # "visual" | "music"
    name: str
    meta: Dict[str, Any] = field(default_factory=dict)   # canvas/bg/tempo/wave...
    nodes: List[Dict[str, Any]] = field(default_factory=list)  # typed primitives


# ── token helpers ──────────────────────────────────────────────────────────
def _tokens(line: str) -> List[str]:
    return re.findall(r'"[^"]*"|\S+', line.strip())


def _opts(tokens: List[str]) -> Dict[str, str]:
    out, i = {}, 0
    while i < len(tokens) - 1:
        out[tokens[i]] = tokens[i + 1]
        i += 2
    return out


def _isnum(s: str) -> bool:
    try:
        float(s); return True
    except ValueError:
        return False


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── block extraction (VokkScript: `visual NAME { ... }` / `music NAME { ... }`)
def extract_blocks(source: str) -> List[Dict[str, str]]:
    blocks, n = [], len(source)
    for m in re.finditer(r"\b(visual|music)\s+([A-Za-z_]\w*)\s*\{", source, re.M):
        kind, name = m.group(1), m.group(2)
        depth, j = 1, m.end()
        while j < n and depth:
            depth += (source[j] == "{") - (source[j] == "}")
            j += 1
        blocks.append({"kind": kind, "name": name, "body": source[m.end():j - 1]})
    return blocks


# ═══════════════════════════════════════════════════════════════════════════
# FORWARD, step 1:  VokkScript code  ->  Vokk IR
# ═══════════════════════════════════════════════════════════════════════════
def _visual_to_ir(name: str, body: str) -> VokkIR:
    ir = VokkIR(kind="visual", name=name,
                meta={"w": 512, "h": 512, "bg": None, "gradients": {}})
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        t = _tokens(line)
        cmd = t[0].lower()
        if cmd == "canvas" and len(t) >= 4 and t[2].lower() == "x":
            ir.meta["w"], ir.meta["h"] = int(float(t[1])), int(float(t[3]))
        elif cmd == "canvas" and len(t) >= 3:
            ir.meta["w"], ir.meta["h"] = int(float(t[1])), int(float(t[2]))
        elif cmd == "background":
            ir.meta["bg"] = t[1]
        elif cmd == "gradient" and len(t) >= 4:
            ir.meta["gradients"][t[1]] = (t[2], t[3])
        elif cmd == "circle" and len(t) >= 4:
            ir.nodes.append({"op": "circle", "cx": t[1], "cy": t[2], "r": t[3], **_opts(t[4:])})
        elif cmd == "rect" and len(t) >= 5:
            ir.nodes.append({"op": "rect", "x": t[1], "y": t[2], "w": t[3], "h": t[4], **_opts(t[5:])})
        elif cmd == "ellipse" and len(t) >= 5:
            ir.nodes.append({"op": "ellipse", "cx": t[1], "cy": t[2], "rx": t[3], "ry": t[4], **_opts(t[5:])})
        elif cmd == "line" and len(t) >= 5:
            ir.nodes.append({"op": "line", "x1": t[1], "y1": t[2], "x2": t[3], "y2": t[4], **_opts(t[5:])})
        elif cmd == "polygon" and len(t) >= 2:
            pts = [x for x in t[1:] if re.fullmatch(r"-?\d+(\.\d+)?,-?\d+(\.\d+)?", x)]
            rest = [x for x in t[1:] if x not in pts]
            ir.nodes.append({"op": "polygon", "points": pts, **_opts(rest)})
        elif cmd == "text" and len(t) >= 4:
            ir.nodes.append({"op": "text", "x": t[1], "y": t[2],
                             "s": t[3].strip('"'), **_opts(t[4:])})
    return ir


def _music_to_ir(name: str, body: str) -> VokkIR:
    ir = VokkIR(kind="music", name=name, meta={"tempo": 120, "wave": "sine"})
    lines = [l.strip() for l in body.splitlines()]

    def beat() -> float:
        return 60.0 / ir.meta["tempo"]

    def parse_play(tokens, times=1):
        seq, i = [], 1
        while i < len(tokens):
            nt = tokens[i]
            has_dur = i + 1 < len(tokens) and _isnum(tokens[i + 1])
            dur = float(tokens[i + 1]) if has_dur else 1.0
            seq.append({"op": "note", "note": nt, "freq": note_to_freq(nt),
                        "beats": dur, "dur": round(dur * beat(), 4), "wave": ir.meta["wave"]})
            i += 2 if has_dur else 1
        for _ in range(times):
            ir.nodes.extend([dict(s) for s in seq])

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line or line.startswith("#"):
            idx += 1; continue
        t = _tokens(line)
        cmd = t[0].lower()
        if cmd == "tempo" and len(t) >= 2:
            ir.meta["tempo"] = float(t[1])
        elif cmd == "wave" and len(t) >= 2:
            ir.meta["wave"] = t[1]
        elif cmd == "play":
            parse_play(t)
        elif cmd == "repeat" and len(t) >= 2 and "{" in line:
            times, inner = int(t[1]), []
            idx += 1
            while idx < len(lines) and "}" not in lines[idx]:
                inner.append(lines[idx]); idx += 1
            for il in inner:
                it = _tokens(il)
                if it and it[0].lower() == "play":
                    parse_play(it, times)
        idx += 1
    return ir


def to_ir(source: str) -> List[VokkIR]:
    """VokkScript -> list of Vokk IR objects."""
    irs = []
    for b in extract_blocks(source):
        irs.append(_visual_to_ir(b["name"], b["body"]) if b["kind"] == "visual"
                   else _music_to_ir(b["name"], b["body"]))
    return irs


# ═══════════════════════════════════════════════════════════════════════════
# FORWARD, step 2:  Vokk IR  ->  image / music artifact
# ═══════════════════════════════════════════════════════════════════════════
def _render_visual(ir: VokkIR) -> Dict[str, Any]:
    w, h = ir.meta["w"], ir.meta["h"]
    grads = ir.meta.get("gradients", {})

    def fillval(v: str) -> str:
        return f"url(#{v})" if v in grads else v

    def attrs(o: Dict[str, str]) -> str:
        a = []
        if "fill" in o:
            a.append(f'fill="{fillval(o["fill"])}"')
        if "stroke" in o:
            a.append(f'stroke="{o["stroke"]}"')
        if "sw" in o:
            a.append(f'stroke-width="{o["sw"]}"')
        if "opacity" in o:
            a.append(f'opacity="{o["opacity"]}"')
        if "rx" in o:
            a.append(f'rx="{o["rx"]}"')
        return " ".join(a)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    if grads:
        parts.append("<defs>" + "".join(
            f'<linearGradient id="{g}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/>'
            f'</linearGradient>' for g, (c1, c2) in grads.items()) + "</defs>")
    if ir.meta.get("bg"):
        parts.append(f'<rect width="{w}" height="{h}" fill="{ir.meta["bg"]}"/>')
    for nd in ir.nodes:
        op = nd["op"]
        if op == "circle":
            parts.append(f'<circle cx="{nd["cx"]}" cy="{nd["cy"]}" r="{nd["r"]}" {attrs(nd)}/>')
        elif op == "rect":
            parts.append(f'<rect x="{nd["x"]}" y="{nd["y"]}" width="{nd["w"]}" height="{nd["h"]}" {attrs(nd)}/>')
        elif op == "ellipse":
            parts.append(f'<ellipse cx="{nd["cx"]}" cy="{nd["cy"]}" rx="{nd["rx"]}" ry="{nd["ry"]}" {attrs(nd)}/>')
        elif op == "line":
            nd.setdefault("stroke", "black")
            parts.append(f'<line x1="{nd["x1"]}" y1="{nd["y1"]}" x2="{nd["x2"]}" y2="{nd["y2"]}" {attrs(nd)}/>')
        elif op == "polygon":
            parts.append(f'<polygon points="{" ".join(nd["points"])}" {attrs(nd)}/>')
        elif op == "text":
            size = nd.get("size", "24")
            family = {"serif": "Georgia, serif", "mono": "ui-monospace, monospace",
                      "display": '"Trebuchet MS", sans-serif'}.get(
                          nd.get("font", ""), nd.get("font") or "sans-serif")
            extra = ""
            if nd.get("weight"):                       # weight bold | 700
                extra += f' font-weight="{nd["weight"]}"'
            if nd.get("style"):                        # style italic
                extra += f' font-style="{nd["style"]}"'
            if nd.get("anchor"):                       # anchor middle | end
                extra += f' text-anchor="{nd["anchor"]}"'
            nd.setdefault("fill", "black")
            parts.append(f'<text x="{nd["x"]}" y="{nd["y"]}" font-size="{size}" '
                         f'font-family="{family}"{extra} {attrs(nd)}>{_esc(nd["s"])}</text>')
    parts.append("</svg>")
    return {"kind": "visual", "name": ir.name, "svg": "".join(parts)}


def _render_music(ir: VokkIR) -> Dict[str, Any]:
    score = [{"freq": n["freq"], "dur": n["dur"], "wave": n.get("wave", ir.meta["wave"])}
             for n in ir.nodes]
    return {"kind": "music", "name": ir.name, "score": score,
            "tempo": ir.meta["tempo"], "wave": ir.meta["wave"],
            "duration_s": round(sum(s["dur"] for s in score), 3)}


def render_ir(ir: VokkIR) -> Dict[str, Any]:
    return _render_visual(ir) if ir.kind == "visual" else _render_music(ir)


# ═══════════════════════════════════════════════════════════════════════════
# REVERSE:  artifact  ->  Vokk IR   (image/music -> vokk-understandable)
# ═══════════════════════════════════════════════════════════════════════════
def svg_to_ir(svg: str, name: str = "Lifted") -> VokkIR:
    """Lift a (VOKK-shaped) SVG back into IR — the reverse half of the pipeline."""
    ir = VokkIR(kind="visual", name=name, meta={"w": 512, "h": 512, "bg": None, "gradients": {}})
    mw = re.search(r'width="(\d+)"', svg); mh = re.search(r'height="(\d+)"', svg)
    if mw: ir.meta["w"] = int(mw.group(1))
    if mh: ir.meta["h"] = int(mh.group(1))
    for tag, attrs in re.findall(r'<(\w+)([^>]*)/?>', svg):
        a = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', attrs))
        if tag == "circle":
            ir.nodes.append({"op": "circle", "cx": a.get("cx"), "cy": a.get("cy"),
                             "r": a.get("r"), "fill": a.get("fill", "")})
        elif tag == "rect" and a.get("width") and int(float(a.get("width", 0))) < ir.meta["w"]:
            ir.nodes.append({"op": "rect", "x": a.get("x"), "y": a.get("y"),
                             "w": a.get("width"), "h": a.get("height"), "fill": a.get("fill", "")})
        elif tag == "line":
            ir.nodes.append({"op": "line", "x1": a.get("x1"), "y1": a.get("y1"),
                             "x2": a.get("x2"), "y2": a.get("y2"),
                             "stroke": a.get("stroke", "black"), "sw": a.get("stroke-width", "1")})
    return ir


def score_to_ir(score: List[Dict[str, Any]], name: str = "Lifted",
                tempo: float = 120, wave: str = "sine") -> VokkIR:
    """Lift a note-score back into IR."""
    ir = VokkIR(kind="music", name=name, meta={"tempo": tempo, "wave": wave})
    beat = 60.0 / tempo
    for s in score:
        ir.nodes.append({"op": "note", "note": freq_to_note(s.get("freq")),
                         "freq": s.get("freq"), "beats": round(s["dur"] / beat, 3),
                         "dur": s["dur"], "wave": s.get("wave", wave)})
    return ir


# ═══════════════════════════════════════════════════════════════════════════
# REVERSE, step 2:  Vokk IR  ->  VokkScript code  (round-trips the pipeline)
# ═══════════════════════════════════════════════════════════════════════════
def emit_vokkscript(ir: VokkIR) -> str:
    L = []
    if ir.kind == "visual":
        L.append(f"visual {ir.name} {{")
        L.append(f'  canvas {ir.meta["w"]} x {ir.meta["h"]}')
        if ir.meta.get("bg"):
            L.append(f'  background {ir.meta["bg"]}')
        for g, (c1, c2) in ir.meta.get("gradients", {}).items():
            L.append(f"  gradient {g} {c1} {c2}")
        for nd in ir.nodes:
            op = nd["op"]
            tail = " ".join(f"{k} {v}" for k, v in nd.items()
                            if k not in ("op", "cx", "cy", "r", "x", "y", "w", "h",
                                         "rx", "ry", "x1", "y1", "x2", "y2", "points", "s"))
            if op == "circle":
                L.append(f'  circle {nd["cx"]} {nd["cy"]} {nd["r"]} {tail}'.rstrip())
            elif op == "rect":
                L.append(f'  rect {nd["x"]} {nd["y"]} {nd["w"]} {nd["h"]} {tail}'.rstrip())
            elif op == "ellipse":
                L.append(f'  ellipse {nd["cx"]} {nd["cy"]} {nd["rx"]} {nd["ry"]} {tail}'.rstrip())
            elif op == "line":
                L.append(f'  line {nd["x1"]} {nd["y1"]} {nd["x2"]} {nd["y2"]} {tail}'.rstrip())
            elif op == "polygon":
                L.append(f'  polygon {" ".join(nd["points"])} {tail}'.rstrip())
            elif op == "text":
                L.append(f'  text {nd["x"]} {nd["y"]} "{nd["s"]}" {tail}'.rstrip())
        L.append("}")
    else:
        L.append(f"music {ir.name} {{")
        L.append(f'  tempo {int(ir.meta["tempo"])}')
        L.append(f'  wave {ir.meta["wave"]}')
        play = " ".join(f'{n["note"]} {int(n["beats"]) if float(n["beats"]).is_integer() else n["beats"]}'
                        for n in ir.nodes)
        L.append(f"  play {play}")
        L.append("}")
    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════════════════
# Public forward entry point
# ═══════════════════════════════════════════════════════════════════════════
def run_vokk(source: str) -> List[Dict[str, Any]]:
    """VokkScript -> IR -> rendered artifacts. Each artifact carries its IR-emitted
    VokkScript back (round-trip) under 'vokkscript' for transparency."""
    out = []
    for ir in to_ir(source):
        try:
            art = render_ir(ir)
            art["vokkscript"] = emit_vokkscript(ir)   # IR round-trip proof
            art["ir_nodes"] = len(ir.nodes)
            out.append(art)
        except Exception as e:
            out.append({"kind": "error", "name": ir.name, "error": str(e)})
    return out


# ── self-test: forward AND reverse ─────────────────────────────────────────
if __name__ == "__main__":
    demo = '''
    visual ManWaving {
        canvas 400 x 400
        background #0e1015
        circle 200 120 40 fill #ffd9a0
        line 200 160 200 270 stroke #ffd9a0 sw 10
        line 200 180 150 130 stroke #ffd9a0 sw 8
        line 200 180 250 230 stroke #ffd9a0 sw 8
        text 110 380 "hi!" fill #5fe0b7 size 28
    }
    music HelloTune {
        tempo 120
        wave triangle
        play C4 1 E4 1 G4 1 C5 2
    }
    '''
    print("── FORWARD: code -> IR -> artifact ──")
    irs = to_ir(demo)
    for ir in irs:
        art = render_ir(ir)
        print(f"{ir.kind} {ir.name}: {ir.meta} | nodes={len(ir.nodes)}")
        if ir.kind == "visual":
            print("  svg bytes:", len(art["svg"]))
        else:
            print("  notes:", len(art["score"]), "freqs:", [s["freq"] for s in art["score"]])

    print("\n── REVERSE: artifact -> IR -> VokkScript ──")
    vis_art = render_ir(irs[0])
    back_ir = svg_to_ir(vis_art["svg"], "RoundTrip")
    print("lifted visual nodes:", len(back_ir.nodes))
    print(emit_vokkscript(back_ir)[:160], "...")

    mus_art = render_ir(irs[1])
    back_mus = score_to_ir(mus_art["score"], "RoundTrip", tempo=120, wave="triangle")
    print("\nlifted music -> VokkScript:")
    print(emit_vokkscript(back_mus))
