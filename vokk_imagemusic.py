#!/usr/bin/env python3
"""
vokk_imagemusic.py — VokkImageMusicScript: VOKK's dedicated language for IMAGES and MUSIC.

Separate from VokkScript (which builds VOKK's mind). This language exists only to
*program* visuals and sound. Its visual model is built for SOFTNESS — radial
gradients, Gaussian blur, translucent layering and lighting — so output looks
painterly/atmospheric, NOT flat papercraft. Fully offline, no API.

    code  ──►  IR  ──►  SVG (soft, blurred, lit)  |  music score (Web Audio)

IMAGE grammar:
  image NAME {
    size W H
    wash #topHex #bottomHex            # smooth vertical gradient background
    blob cx cy r #hex [blur B] [opacity O]      # soft radial orb (gradient -> transparent)
    glow cx cy r #hex [intensity I]             # luminous light bloom
    stroke x1 y1 x2 y2 #hex width W [blur B]    # soft painterly stroke
    field pts.. #hex [blur B] [opacity O]       # soft polygon region (blurred edges)
    light cx cy r #hex                          # bright highlight
    text x y "s" #hex size N [weight bold] [font serif|mono|display]
  }

MUSIC grammar:
  song NAME {
    tempo BPM
    wave sine|triangle|square|sawtooth
    play NOTE DUR ...        # C4 D#4 A3; "_" = rest; DUR in beats
    repeat N { play ... }
  }
"""

import re
import math
from typing import List, Dict, Any, Optional

_NOTE_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_to_freq(note: str) -> Optional[float]:
    note = note.strip()
    if note in ("_", "rest", "-"):
        return None
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", note)
    if not m:
        return None
    semis = _NOTE_SEMITONE[m.group(1).upper()] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    midi = semis + (int(m.group(3)) + 1) * 12
    return round(440.0 * (2 ** ((midi - 69) / 12)), 3)


def _tok(line: str) -> List[str]:
    return re.findall(r'"[^"]*"|\S+', line.strip())


def _opts(t: List[str]) -> Dict[str, str]:
    o, i = {}, 0
    while i < len(t) - 1:
        o[t[i]] = t[i + 1]; i += 2
    return o


def _isnum(s: str) -> bool:
    try:
        float(s); return True
    except ValueError:
        return False


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _blocks(source: str, head: str) -> List[Dict[str, str]]:
    out, n = [], len(source)
    for m in re.finditer(r"\b(" + head + r")\s+([A-Za-z_]\w*)\s*\{", source, re.M):
        depth, j = 1, m.end()
        while j < n and depth:
            depth += (source[j] == "{") - (source[j] == "}")
            j += 1
        out.append({"name": m.group(2), "body": source[m.end():j - 1]})
    return out


# ── IMAGE: render to SOFT svg (gradients + blur + layering) ─────────────────
def _render_image(name: str, body: str) -> Dict[str, Any]:
    w = h = 512
    defs, layers = [], []
    gid = [0]

    def newid(p):
        gid[0] += 1
        return f"{p}{gid[0]}"

    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") and " " not in line:
            continue
        t = _tok(line)
        cmd = t[0].lower()
        if cmd == "size" and len(t) >= 3:
            w, h = int(float(t[1])), int(float(t[2]))
        elif cmd == "wash" and len(t) >= 3:
            gi = newid("wash")
            defs.append(f'<linearGradient id="{gi}" x1="0" y1="0" x2="0" y2="1">'
                        f'<stop offset="0%" stop-color="{t[1]}"/>'
                        f'<stop offset="100%" stop-color="{t[2]}"/></linearGradient>')
            layers.append((-1, f'<rect width="{w}" height="{h}" fill="url(#{gi})"/>'))
        elif cmd == "blob" and len(t) >= 5:
            cx, cy, r, col = t[1], t[2], t[3], t[4]; o = _opts(t[5:])
            op = o.get("opacity", "0.9"); blur = float(o.get("blur", "0"))
            gi = newid("blob")
            defs.append(f'<radialGradient id="{gi}"><stop offset="0%" stop-color="{col}" stop-opacity="{op}"/>'
                        f'<stop offset="65%" stop-color="{col}" stop-opacity="{float(op)*0.5:.2f}"/>'
                        f'<stop offset="100%" stop-color="{col}" stop-opacity="0"/></radialGradient>')
            fl = _blur_filter(defs, newid, blur)
            layers.append((0, f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#{gi})"{fl}/>'))
        elif cmd == "glow" and len(t) >= 5:
            cx, cy, r, col = t[1], t[2], t[3], t[4]; o = _opts(t[5:])
            inten = float(o.get("intensity", "1"))
            gi = newid("glow")
            defs.append(f'<radialGradient id="{gi}"><stop offset="0%" stop-color="{col}" stop-opacity="{min(1,0.85*inten):.2f}"/>'
                        f'<stop offset="40%" stop-color="{col}" stop-opacity="{min(1,0.45*inten):.2f}"/>'
                        f'<stop offset="100%" stop-color="{col}" stop-opacity="0"/></radialGradient>')
            layers.append((1, f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#{gi})"/>'))
        elif cmd == "light" and len(t) >= 5:
            cx, cy, r, col = t[1], t[2], t[3], t[4]
            gi = newid("light")
            defs.append(f'<radialGradient id="{gi}"><stop offset="0%" stop-color="{col}" stop-opacity="0.95"/>'
                        f'<stop offset="100%" stop-color="{col}" stop-opacity="0"/></radialGradient>')
            layers.append((2, f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#{gi})"/>'))
        elif cmd == "stroke" and len(t) >= 6:
            o = _opts(t[5:]); width = o.get("width", "8"); blur = float(o.get("blur", "1.5"))
            fl = _blur_filter(defs, newid, blur)
            layers.append((0, f'<line x1="{t[1]}" y1="{t[2]}" x2="{t[3]}" y2="{t[4]}" '
                              f'stroke="{t[5] if not t[5][0].isalpha() else t[5]}" '
                              f'stroke-width="{width}" stroke-linecap="round"{fl}/>'))
        elif cmd == "field" and len(t) >= 2:
            pts = [x for x in t[1:] if re.fullmatch(r"-?\d+(\.\d+)?,-?\d+(\.\d+)?", x)]
            rest = [x for x in t[1:] if x not in pts]
            col = next((x for x in rest if x.startswith("#")), "#888")
            o = _opts([x for x in rest if not x.startswith("#")])
            blur = float(o.get("blur", "6")); op = o.get("opacity", "0.7")
            fl = _blur_filter(defs, newid, blur)
            layers.append((0, f'<polygon points="{" ".join(pts)}" fill="{col}" opacity="{op}"{fl}/>'))
        elif cmd == "text" and len(t) >= 4:
            o = _opts(t[4:]); size = o.get("size", "24")
            fam = {"serif": "Georgia,serif", "mono": "ui-monospace,monospace",
                   "display": '"Trebuchet MS",sans-serif'}.get(o.get("font", ""), "sans-serif")
            wt = f' font-weight="{o["weight"]}"' if "weight" in o else ""
            layers.append((3, f'<text x="{t[1]}" y="{t[2]}" font-size="{size}" font-family="{fam}"{wt} '
                              f'fill="{o.get("fill","#fff")}">{_esc(t[3].strip(chr(34)))}</text>'))

    layers.sort(key=lambda p: p[0])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
           + ("<defs>" + "".join(defs) + "</defs>" if defs else "")
           + "".join(b for _, b in layers) + "</svg>")
    return {"kind": "image", "name": name, "svg": svg}


def _blur_filter(defs, newid, blur):
    if blur <= 0:
        return ""
    fi = newid("blur")
    defs.append(f'<filter id="{fi}" x="-40%" y="-40%" width="180%" height="180%">'
                f'<feGaussianBlur stdDeviation="{blur}"/></filter>')
    return f' filter="url(#{fi})"'


# ── MUSIC: song -> score ────────────────────────────────────────────────────
def _render_song(name: str, body: str) -> Dict[str, Any]:
    tempo, wave, notes = 120, "sine", []
    lines = [l.strip() for l in body.splitlines()]

    def beat():
        return 60.0 / tempo

    def play(t, times=1):
        seq, i = [], 1
        while i < len(t):
            has = i + 1 < len(t) and _isnum(t[i + 1])
            dur = float(t[i + 1]) if has else 1.0
            seq.append({"freq": note_to_freq(t[i]), "dur": round(dur * beat(), 4), "wave": wave})
            i += 2 if has else 1
        for _ in range(times):
            notes.extend(dict(s) for s in seq)

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line or line.startswith("#"):
            idx += 1; continue
        t = _tok(line); c = t[0].lower()
        if c == "tempo" and len(t) >= 2:
            tempo = float(t[1])
        elif c == "wave" and len(t) >= 2:
            wave = t[1]
        elif c == "play":
            play(t)
        elif c == "repeat" and len(t) >= 2 and "{" in line:
            times, inner = int(t[1]), []
            idx += 1
            while idx < len(lines) and "}" not in lines[idx]:
                inner.append(lines[idx]); idx += 1
            for il in inner:
                it = _tok(il)
                if it and it[0].lower() == "play":
                    play(it, times)
        idx += 1
    return {"kind": "music", "name": name, "score": notes, "tempo": tempo, "wave": wave,
            "duration_s": round(sum(n["dur"] for n in notes), 3)}


# ── public ──────────────────────────────────────────────────────────────────
def run_imagemusic(source: str) -> List[Dict[str, Any]]:
    out = []
    for b in _blocks(source, "image"):
        try:
            out.append(_render_image(b["name"], b["body"]))
        except Exception as e:
            out.append({"kind": "error", "name": b["name"], "error": str(e)})
    for b in _blocks(source, "song"):
        try:
            out.append(_render_song(b["name"], b["body"]))
        except Exception as e:
            out.append({"kind": "error", "name": b["name"], "error": str(e)})
    return out


if __name__ == "__main__":
    demo = '''
    image Dawn {
        size 480 360
        wash #1a2540 #e8a36b
        glow 360 100 200 #fff2c4 intensity 1.4
        light 360 100 40 #ffffff
        field 0,250 480,230 480,360 0,360 #2a2233 blur 10 opacity 0.85
        blob 120 300 90 #3a3550 blur 8 opacity 0.6
    }
    song Calm {
        tempo 90
        wave sine
        play C4 1 E4 1 G4 1 E4 1 C4 2
    }
    '''
    for a in run_imagemusic(demo):
        if a["kind"] == "image":
            print("image", a["name"], "svg", len(a["svg"]), "bytes")
        elif a["kind"] == "music":
            print("music", a["name"], len(a["score"]), "notes")
        else:
            print("err", a)
