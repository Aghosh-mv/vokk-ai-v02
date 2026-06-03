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
import base64
import io
import importlib.util
import os
from pathlib import Path
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


_MULTI_STYLE_PATHS = [
    Path(os.environ.get("VOKK_MULTI_STYLE_ENGINE", "")) if os.environ.get("VOKK_MULTI_STYLE_ENGINE") else None,
    Path(__file__).with_name("multi_style_image_engine.py"),
    Path("/Users/tinkerspace/Downloads/multi_style_image_engine.py"),
]


def _load_multistyle_engine():
    path = next((p for p in _MULTI_STYLE_PATHS if p and p.exists()), None)
    if not path:
        return None, "Multi_Style Image_Engine not found. Set VOKK_MULTI_STYLE_ENGINE or place multi_style_image_engine.py beside vokk.py."
    try:
        spec = importlib.util.spec_from_file_location("vokk_multi_style_image_engine", str(path))
        if not spec or not spec.loader:
            return None, f"Could not load engine from {path}"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, ""
    except Exception as exc:
        return None, f"Multi_Style Image_Engine unavailable: {exc}"


def _multistyle_options(body: str) -> Optional[Dict[str, Any]]:
    opts = {"style": None, "seed": None, "width": 512, "height": 384}
    for raw in body.splitlines():
        t = _tok(raw)
        if not t:
            continue
        cmd = t[0].lower()
        if cmd in {"style", "multistyle", "engine"} and len(t) >= 2:
            value = t[-1].lower() if cmd == "engine" and len(t) >= 3 else t[1].lower()
            if value in {"photorealistic", "photo", "realistic"}:
                opts["style"] = "photorealistic"
            elif value in {"pencil", "drawing", "graphite"}:
                opts["style"] = "pencil"
            elif value in {"watercolor", "watercolour", "paint"}:
                opts["style"] = "watercolor"
            elif value in {"cartoon", "vector"}:
                opts["style"] = "cartoon"
            elif value in {"pixel", "pixelart", "retro"}:
                opts["style"] = "pixel"
        elif cmd == "size" and len(t) >= 3:
            opts["width"], opts["height"] = int(float(t[1])), int(float(t[2]))
        elif cmd == "seed" and len(t) >= 2:
            try:
                opts["seed"] = int(float(t[1]))
            except ValueError:
                opts["seed"] = None
    return opts if opts["style"] else None


def _render_multistyle_image(name: str, body: str) -> Optional[Dict[str, Any]]:
    opts = _multistyle_options(body)
    if not opts:
        return None
    mod, err = _load_multistyle_engine()
    if not mod:
        fallback = _fallback_multistyle_png(name, opts)
        if fallback:
            fallback["warning"] = err
            return fallback
        return {"kind": "image", "name": name, "engine": "multi_style", "style": opts["style"], "error": err,
                "missing_dependency": "Install Pillow and numpy, then restart VOKK."}
    try:
        w, h, seed, style = opts["width"], opts["height"], opts["seed"], opts["style"]
        if style == "photorealistic":
            img = mod.PhotorealisticRenderer(w, h, seed).generate_photorealistic_landscape()
        elif style == "pencil":
            img = mod.PencilDrawingRenderer(w, h, seed).generate_pencil_landscape("mountains")
        elif style == "watercolor":
            img = mod.WatercolorRenderer(w, h, seed).generate_watercolor_landscape()
        elif style == "cartoon":
            renderer = mod.CartoonRenderer(w, h, seed)
            bg = renderer.generate_cartoon_background("gradient").convert("RGBA")
            scene = renderer.generate_cartoon_scene("nature")
            char = renderer.generate_cartoon_character("animal")
            img = mod.Image.alpha_composite(mod.Image.alpha_composite(bg, scene), char).convert("RGB")
        elif style == "pixel":
            img = mod.PixelArtRenderer(w, h, seed).generate_pixel_landscape()
        else:
            return None
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return {
            "kind": "image",
            "name": name,
            "engine": "multi_style",
            "style": style,
            "png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        }
    except Exception as exc:
        fallback = _fallback_multistyle_png(name, opts)
        if fallback:
            fallback["warning"] = f"Downloaded engine failed for {opts['style']}: {exc}. Used VOKK PIL fallback."
            return fallback
        return {"kind": "image", "name": name, "engine": "multi_style", "style": opts["style"], "error": str(exc)}


def _png_result(name: str, style: str, img, engine: str = "multi_style_fallback") -> Dict[str, Any]:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"kind": "image", "name": name, "engine": engine, "style": style,
            "png_b64": base64.b64encode(buf.getvalue()).decode("ascii")}


def _fallback_multistyle_png(name: str, opts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception:
        return None
    style, w, h = opts["style"], int(opts["width"]), int(opts["height"])
    rnd_seed = opts.get("seed")
    import random as _random
    rng = _random.Random(rnd_seed)
    if style == "pixel":
        small = Image.new("RGB", (max(24, w // 8), max(18, h // 8)), "#1d2b53")
        d = ImageDraw.Draw(small)
        for y in range(small.height):
            col = "#29adff" if y < small.height * .45 else "#00e436"
            d.rectangle((0, y, small.width, y), fill=col)
        for _ in range(45):
            x, y = rng.randrange(small.width), rng.randrange(small.height)
            d.rectangle((x, y, min(small.width, x + rng.randrange(1, 4)), min(small.height, y + rng.randrange(1, 4))),
                        fill=rng.choice(["#ffec27", "#ff004d", "#7e2553", "#fff1e8"]))
        return _png_result(name, style, small.resize((w, h), Image.Resampling.NEAREST))
    img = Image.new("RGB", (w, h), "#f7f3ea")
    d = ImageDraw.Draw(img, "RGBA")
    if style == "photorealistic":
        for y in range(h):
            t = y / max(1, h - 1)
            r, g, b = int(80 + 130 * t), int(145 + 55 * t), int(210 - 120 * t)
            d.line((0, y, w, y), fill=(r, g, b, 255))
        for i, base in enumerate([.54, .65, .76]):
            pts = [(0, h * base)]
            for x in range(0, w + 40, 40):
                pts.append((x, h * base - rng.randrange(10, 70)))
            pts += [(w, h), (0, h)]
            shade = 80 + i * 35
            d.polygon(pts, fill=(shade, 95 + i * 25, 90 + i * 20, 210))
        d.ellipse((w*.66, h*.12, w*.83, h*.34), fill=(255, 235, 170, 170))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    elif style == "pencil":
        img = Image.new("L", (w, h), 242)
        d = ImageDraw.Draw(img, "L")
        for _ in range(900):
            x, y = rng.randrange(w), rng.randrange(h)
            d.point((x, y), fill=rng.randrange(170, 245))
        for i in range(24):
            y = int(h * .45 + i * 5)
            d.line((20, y, w - 20, y + rng.randrange(-24, 24)), fill=90 + i * 3, width=1)
        for _ in range(90):
            x = rng.randrange(0, w)
            y = rng.randrange(int(h*.35), h)
            d.line((x, y, x + rng.randrange(-60, 60), y + rng.randrange(-20, 35)), fill=rng.randrange(55, 155), width=1)
        img = img.filter(ImageFilter.GaussianBlur(.25)).convert("RGB")
    elif style == "watercolor":
        img = Image.new("RGBA", (w, h), (250, 246, 235, 255))
        d = ImageDraw.Draw(img, "RGBA")
        for _ in range(70):
            x, y, r = rng.randrange(w), rng.randrange(h), rng.randrange(20, 90)
            col = rng.choice([(78, 170, 205, 52), (230, 115, 91, 48), (104, 180, 120, 46), (152, 115, 210, 42)])
            d.ellipse((x-r, y-r, x+r, y+r), fill=col)
        for _ in range(18):
            x1, y1 = rng.randrange(w), rng.randrange(h)
            d.line((x1, y1, x1 + rng.randrange(-120, 120), y1 + rng.randrange(-80, 80)),
                   fill=rng.choice([(40, 100, 150, 70), (160, 70, 90, 62)]), width=rng.randrange(3, 10))
        img = img.filter(ImageFilter.GaussianBlur(2.2)).convert("RGB")
    elif style == "cartoon":
        for y in range(h):
            t = y / max(1, h - 1)
            d.line((0, y, w, y), fill=(int(118 + 70*t), int(207 - 60*t), int(255 - 80*t), 255))
        d.rectangle((0, int(h*.66), w, h), fill=(80, 205, 100, 255))
        d.ellipse((w*.35, h*.32, w*.65, h*.62), fill=(255, 214, 80, 255), outline=(50, 40, 35, 255), width=5)
        d.ellipse((w*.43, h*.42, w*.47, h*.46), fill=(30, 30, 30, 255))
        d.ellipse((w*.53, h*.42, w*.57, h*.46), fill=(30, 30, 30, 255))
        d.arc((w*.43, h*.44, w*.58, h*.55), 20, 160, fill=(30, 30, 30, 255), width=4)
    else:
        return None
    return _png_result(name, style, img)


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
            styled = _render_multistyle_image(b["name"], b["body"])
            out.append(styled if styled else _render_image(b["name"], b["body"]))
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
