#!/usr/bin/env python3
"""
vokk_raster.py — VOKK's procedural raster engine (real pixels, stdlib only).

This is the second render target of the VokkScript pipeline:

    VokkScript `scene { ... }`  ──►  Vokk IR  ──►  RGB pixel buffer  ──►  PNG (base64)

Unlike the SVG target (crisp vector shapes), this target paints actual pixels with
photographic techniques — vertical light gradients, radial glow, value-noise fog,
atmospheric depth, and film grain. No PIL, no numpy, no API: a hand-written PNG
encoder over zlib. The result is VOKK's signature "atmospheric / luminous" art —
dreamy, textured, photographic in feel (not clip-art, not a literal photo).

scene grammar:
    scene NAME {
        size W H
        seed N                       # optional deterministic variation
        sky  #top #bottom            # vertical gradient fill (the base light)
        band y0 y1 #color [soft S]   # horizontal field (horizon/ground/water), soft edge
        ridge y amp rough #color [soft S] [seed N]   # mountain / dune / treeline silhouette
        cloud cx cy rx ry #color [opacity O] [blur B] # soft elliptical cloud mass
        water y #top #bottom [reflect R] [ripple P]   # water gradient with reflected sky/light
        cityline y #color [density D] [maxh H] [glow G] # skyline silhouette + sparse window glow
        stars amount [#color] [size S]   # night-sky star field
        rain amount [angle A] [len L] [#color]   # diagonal rain streaks
        snow amount [size S] [#color]             # drifting snow flecks
        glow cx cy radius #color [intensity I]   # radial light source / bloom
        sun  cx cy radius #color     # bright core + halo (shorthand glow)
        fog  amount [#tint]          # value-noise haze, 0..1
        haze y0 y1 amount            # banded atmospheric depth
        grain amount                 # film grain, 0..1
        vignette amount              # darkened edges, 0..1
    }
"""

import re
import math
import zlib
import struct
import base64
from typing import List, Dict, Any, Optional, Tuple


# ── color helpers ──────────────────────────────────────────────────────────
def _hex(c: str) -> Tuple[int, int, int]:
    c = (c or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return 0, 0, 0


def _lerp(a, b, t):
    return a + (b - a) * t


def _clamp8(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def _blend(a: float, b: float, t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return a + (b - a) * t


# ── value noise (hash lattice + bilinear), deterministic, no deps ───────────
def _h2(x: int, y: int, seed: int = 1) -> float:
    n = (x * 374761393 + y * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


def _vnoise(x: float, y: float, seed: int = 1) -> float:
    xi, yi = int(math.floor(x)), int(math.floor(y))
    xf, yf = x - xi, y - yi
    u = xf * xf * (3 - 2 * xf)
    v = yf * yf * (3 - 2 * yf)
    a = _h2(xi, yi, seed); b = _h2(xi + 1, yi, seed)
    c = _h2(xi, yi + 1, seed); d = _h2(xi + 1, yi + 1, seed)
    return _lerp(_lerp(a, b, u), _lerp(c, d, u), v)


def _fbm(x: float, y: float, seed: int = 1, octaves: int = 4) -> float:
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        total += amp * _vnoise(x * freq, y * freq, seed)
        norm += amp; amp *= 0.5; freq *= 2.0
    return total / norm


# ── minimal PNG encoder (stdlib zlib) ───────────────────────────────────────
def _png(width: int, height: int, rgb: bytearray) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)                          # filter type 0 (None)
        raw.extend(rgb[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)   # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


# ── parse a scene block into IR-ish op list ─────────────────────────────────
def parse_scene(name: str, body: str) -> Dict[str, Any]:
    scene = {"name": name, "w": 640, "h": 480, "seed": None, "ops": []}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") and not re.match(r"#\w", line):
            # allow leading '#rrggbb' tokens; only skip true comments
            if line.startswith("#") and " " not in line:
                pass
            else:
                continue
        if not line or (line.startswith("#") and " " not in line):
            continue
        t = re.findall(r'"[^"]*"|\S+', line)
        cmd = t[0].lower()
        if cmd == "size" and len(t) >= 3:
            scene["w"], scene["h"] = int(float(t[1])), int(float(t[2]))
        elif cmd == "seed" and len(t) >= 2:
            try:
                scene["seed"] = int(float(t[1]))
            except Exception:
                pass
        else:
            scene["ops"].append(t)
    # clamp size for speed/safety
    scene["w"] = max(64, min(scene["w"], 960))
    scene["h"] = max(64, min(scene["h"], 720))
    return scene


def _num(t, i, default=0.0):
    try:
        return float(t[i])
    except Exception:
        return default


# ── the renderer: scene -> RGB pixel buffer -> PNG base64 ───────────────────
def render_scene(scene: Dict[str, Any]) -> Dict[str, Any]:
    w, h, ops = scene["w"], scene["h"], scene["ops"]
    seed = scene.get("seed") or ((abs(hash(scene["name"])) % 9999) + 1)

    # accumulate as float RGB planes
    R = [0.0] * (w * h); G = [0.0] * (w * h); B = [0.0] * (w * h)

    # base sky (first sky op, else dark)
    top, bot = (18, 20, 30), (40, 36, 48)
    for t in ops:
        if t[0].lower() == "sky" and len(t) >= 3:
            top, bot = _hex(t[1]), _hex(t[2]); break
    for y in range(h):
        ty = y / max(1, h - 1)
        r = _lerp(top[0], bot[0], ty); g = _lerp(top[1], bot[1], ty); b = _lerp(top[2], bot[2], ty)
        base = y * w
        for x in range(w):
            idx = base + x
            R[idx] = r; G[idx] = g; B[idx] = b

    # subsequent painterly ops
    for t in ops:
        cmd = t[0].lower()
        if cmd == "band" and len(t) >= 4:
            y0, y1 = int(_num(t, 1)), int(_num(t, 2)); col = _hex(t[3])
            soft = _num(t, t.index("soft") + 1) if "soft" in t else 8.0
            y0, y1 = max(0, min(y0, h)), max(0, min(y1, h))
            for y in range(min(y0, y1), max(y0, y1)):
                # soft alpha near edges
                edge = min(y - min(y0, y1), max(y0, y1) - 1 - y)
                a = 1.0 if soft <= 0 else min(1.0, (edge + 1) / soft)
                base = y * w
                for x in range(w):
                    idx = base + x
                    R[idx] = _lerp(R[idx], col[0], a)
                    G[idx] = _lerp(G[idx], col[1], a)
                    B[idx] = _lerp(B[idx], col[2], a)
        elif cmd == "ridge" and len(t) >= 5:
            base_y = _num(t, 1); amp = max(2.0, _num(t, 2)); rough = max(0.2, _num(t, 3))
            col = _hex(t[4]); soft = _num(t, t.index("soft") + 1) if "soft" in t else 10.0
            layer_seed = int(_num(t, t.index("seed") + 1, seed + 17)) if "seed" in t else seed + 17
            scale = rough / max(160.0, w * 0.42)
            heights = [base_y - amp * (0.12 + 0.88 * _fbm(x * scale, layer_seed * 0.013, layer_seed, 5)) for x in range(w)]
            for x in range(w):
                ridge_y = heights[x]
                ys = max(0, int(ridge_y - soft * 1.8))
                for y in range(ys, h):
                    idx = y * w + x
                    if y < ridge_y:
                        a = max(0.0, 1.0 - ((ridge_y - y) / max(1.0, soft)))
                        a *= 0.7
                    else:
                        a = 1.0
                    haze = 0.92 + 0.08 * _fbm(x * 0.02, y * 0.02, layer_seed + 9, 3)
                    R[idx] = _lerp(R[idx], col[0] * haze, a)
                    G[idx] = _lerp(G[idx], col[1] * haze, a)
                    B[idx] = _lerp(B[idx], col[2] * haze, a)
        elif cmd == "cloud" and len(t) >= 6:
            cx, cy, rx, ry = _num(t, 1), _num(t, 2), max(8.0, _num(t, 3)), max(5.0, _num(t, 4))
            col = _hex(t[5]); opacity = _num(t, t.index("opacity") + 1) if "opacity" in t else 0.42
            blur = max(0.5, _num(t, t.index("blur") + 1)) if "blur" in t else 18.0
            xs, xe = max(0, int(cx - rx - blur * 2)), min(w, int(cx + rx + blur * 2))
            ys, ye = max(0, int(cy - ry - blur * 2)), min(h, int(cy + ry + blur * 2))
            for y in range(ys, ye):
                base = y * w
                ny = (y - cy) / max(1.0, ry)
                for x in range(xs, xe):
                    nx = (x - cx) / max(1.0, rx)
                    d = nx * nx + ny * ny
                    if d > 4.0:
                        continue
                    edge = math.exp(-d * (1.3 + blur * 0.01)) * opacity
                    puff = 0.75 + 0.35 * _fbm(x * 0.03, y * 0.03, seed + 31, 4)
                    a = edge * puff
                    idx = base + x
                    R[idx] = _lerp(R[idx], col[0], a)
                    G[idx] = _lerp(G[idx], col[1], a)
                    B[idx] = _lerp(B[idx], col[2], a)
        elif cmd == "water" and len(t) >= 4:
            horizon = max(0, min(h - 1, int(_num(t, 1))))
            topc, botc = _hex(t[2]), _hex(t[3])
            reflect = _num(t, t.index("reflect") + 1) if "reflect" in t else 0.42
            ripple = _num(t, t.index("ripple") + 1) if "ripple" in t else 0.06
            for y in range(horizon, h):
                ty = (y - horizon) / max(1, h - horizon - 1)
                base = y * w
                for x in range(w):
                    idx = base + x
                    wave = math.sin((x * 0.045) + (y - horizon) * 0.08 + seed * 0.1) * ripple
                    r = _lerp(topc[0], botc[0], min(1.0, max(0.0, ty + wave)))
                    g = _lerp(topc[1], botc[1], min(1.0, max(0.0, ty + wave)))
                    b = _lerp(topc[2], botc[2], min(1.0, max(0.0, ty + wave)))
                    R[idx] = _lerp(R[idx], r, 0.72)
                    G[idx] = _lerp(G[idx], g, 0.72)
                    B[idx] = _lerp(B[idx], b, 0.72)
                    if reflect > 0:
                        yy = max(0, min(h - 1, horizon - int((y - horizon) * (0.75 + 0.25 * _fbm(x * 0.02, y * 0.02, seed + 5, 2)))))
                        src = yy * w + min(w - 1, max(0, x + int(math.sin(y * 0.08 + seed) * 2)))
                        shimmer = 0.7 + 0.3 * math.sin((x + seed) * 0.12 + ty * 18.0)
                        a = reflect * (1.0 - ty) * shimmer
                        R[idx] = _lerp(R[idx], R[src], a)
                        G[idx] = _lerp(G[idx], G[src], a)
                        B[idx] = _lerp(B[idx], B[src], a)
        elif cmd == "cityline" and len(t) >= 3:
            base_y = max(0, min(h - 1, int(_num(t, 1)))); col = _hex(t[2])
            density = _num(t, t.index("density") + 1) if "density" in t else 0.72
            maxh = max(24.0, _num(t, t.index("maxh") + 1)) if "maxh" in t else h * 0.24
            glow = _num(t, t.index("glow") + 1) if "glow" in t else 0.18
            x = 0
            while x < w:
                bw = max(3, int(3 + _h2(x, base_y, seed + 23) * 16))
                if _h2(x + 17, base_y + 9, seed + 29) > density:
                    x += bw
                    continue
                bh = int(10 + _h2(x + 3, base_y + 7, seed + 19) * maxh)
                for yy in range(max(0, base_y - bh), base_y):
                    row = yy * w
                    for xx in range(x, min(w, x + bw)):
                        idx = row + xx
                        depth = 0.92 + 0.08 * ((yy - (base_y - bh)) / max(1, bh))
                        R[idx] = _lerp(R[idx], col[0] * depth, 0.96)
                        G[idx] = _lerp(G[idx], col[1] * depth, 0.96)
                        B[idx] = _lerp(B[idx], col[2] * depth, 0.96)
                        if glow > 0 and ((xx - x) % 3 == 1) and ((base_y - yy) % 7 == 2) and _h2(xx, yy, seed + 41) > 0.68:
                            wcol = (255, 216, 146)
                            a = glow * (0.5 + 0.5 * _h2(xx, yy, seed + 43))
                            R[idx] = _lerp(R[idx], wcol[0], a)
                            G[idx] = _lerp(G[idx], wcol[1], a)
                            B[idx] = _lerp(B[idx], wcol[2], a)
                x += bw
        elif cmd == "stars" and len(t) >= 2:
            amt = max(0.0, _num(t, 1)); col = _hex(t[2]) if len(t) >= 3 and t[2].startswith("#") else (235, 238, 255)
            size = _num(t, t.index("size") + 1) if "size" in t else 1.4
            count = int(max(12, min(1600, w * h * 0.00032 * (0.35 + amt))))
            for i in range(count):
                sx = int(_h2(i, seed, seed + 47) * (w - 1))
                sy = int((_h2(i, seed + 11, seed + 53) ** 1.8) * max(1, h * 0.6))
                glow = 0.55 + _h2(i, seed + 17, seed + 59)
                rad = 1 if size < 1.5 else 2
                for oy in range(-rad, rad + 1):
                    yy = sy + oy
                    if yy < 0 or yy >= h:
                        continue
                    row = yy * w
                    for ox in range(-rad, rad + 1):
                        xx = sx + ox
                        if xx < 0 or xx >= w:
                            continue
                        d2 = ox * ox + oy * oy
                        a = math.exp(-d2 / max(0.8, size)) * glow
                        idx = row + xx
                        R[idx] += col[0] * a * 0.9
                        G[idx] += col[1] * a * 0.9
                        B[idx] += col[2] * a
        elif cmd in ("glow", "sun") and len(t) >= 5:
            cx, cy, rad = _num(t, 1), _num(t, 2), max(1.0, _num(t, 3))
            col = _hex(t[4])
            inten = _num(t, t.index("intensity") + 1) if "intensity" in t else (1.4 if cmd == "sun" else 1.0)
            r2 = rad * rad
            reach = rad * 4.0                                   # box big enough for gaussian to vanish
            core2 = r2 * 0.32                                   # bright solid core (sun only)
            ys, ye = max(0, int(cy - reach)), min(h, int(cy + reach))
            xs, xe = max(0, int(cx - reach)), min(w, int(cx + reach))
            for y in range(ys, ye):
                base = y * w
                dy2 = (y - cy) ** 2
                for x in range(xs, xe):
                    d2 = (x - cx) ** 2 + dy2
                    fall = math.exp(-d2 / (2 * r2)) * inten     # gaussian bloom, fades to ~0
                    idx = base + x
                    if cmd == "sun" and d2 < core2:             # opaque luminous core
                        k = 1.0 - (d2 / core2) * 0.25
                        R[idx] = _lerp(R[idx], col[0], k)
                        G[idx] = _lerp(G[idx], col[1], k)
                        B[idx] = _lerp(B[idx], col[2], k)
                    else:                                        # additive halo
                        R[idx] += col[0] * fall * 0.6
                        G[idx] += col[1] * fall * 0.6
                        B[idx] += col[2] * fall * 0.6
        elif cmd == "fog" and len(t) >= 2:
            amt = _num(t, 1); tint = _hex(t[2]) if len(t) >= 3 else (220, 220, 230)
            scale = 1.0 / max(8.0, w / 6.0)
            for y in range(h):
                base = y * w
                for x in range(w):
                    n = _fbm(x * scale, y * scale, seed, 4)
                    a = amt * (0.35 + 0.65 * n)
                    idx = base + x
                    R[idx] = _lerp(R[idx], tint[0], a)
                    G[idx] = _lerp(G[idx], tint[1], a)
                    B[idx] = _lerp(B[idx], tint[2], a)
        elif cmd == "haze" and len(t) >= 4:
            y0, y1, amt = int(_num(t, 1)), int(_num(t, 2)), _num(t, 3)
            tint = (235, 230, 225)
            for y in range(max(0, min(y0, y1)), min(h, max(y0, y1))):
                ty = (y - y0) / max(1, (y1 - y0))
                a = amt * ty
                base = y * w
                for x in range(w):
                    idx = base + x
                    R[idx] = _lerp(R[idx], tint[0], a)
                    G[idx] = _lerp(G[idx], tint[1], a)
                    B[idx] = _lerp(B[idx], tint[2], a)
        elif cmd == "rain" and len(t) >= 2:
            amt = max(0.0, _num(t, 1)); angle = math.radians(_num(t, t.index("angle") + 1)) if "angle" in t else math.radians(-18)
            length = max(6, int(_num(t, t.index("len") + 1))) if "len" in t else 18
            col = next((_hex(tok) for tok in t[2:] if tok.startswith("#")), (196, 210, 228))
            count = int(max(40, min(6000, w * h * 0.00055 * (0.25 + amt))))
            dx = math.cos(angle) * length; dy = math.sin(angle) * length
            for i in range(count):
                x0 = int(_h2(i, seed + 61, seed + 67) * (w - 1))
                y0 = int(_h2(i, seed + 71, seed + 73) * (h - 1))
                for s in range(length):
                    xx = int(x0 + dx * (s / max(1, length - 1)))
                    yy = int(y0 + dy * (s / max(1, length - 1)))
                    if 0 <= xx < w and 0 <= yy < h:
                        idx = yy * w + xx
                        a = (1.0 - s / max(1, length)) * 0.35
                        R[idx] = _lerp(R[idx], col[0], a)
                        G[idx] = _lerp(G[idx], col[1], a)
                        B[idx] = _lerp(B[idx], col[2], a)
        elif cmd == "snow" and len(t) >= 2:
            amt = max(0.0, _num(t, 1)); size = _num(t, t.index("size") + 1) if "size" in t else 1.8
            col = next((_hex(tok) for tok in t[2:] if tok.startswith("#")), (245, 247, 255))
            count = int(max(20, min(5000, w * h * 0.00022 * (0.35 + amt))))
            rad = 1 if size < 1.8 else 2
            for i in range(count):
                sx = int(_h2(i, seed + 79, seed + 83) * (w - 1))
                sy = int(_h2(i, seed + 89, seed + 97) * (h - 1))
                glow = 0.35 + 0.65 * _h2(i, seed + 101, seed + 103)
                for oy in range(-rad, rad + 1):
                    yy = sy + oy
                    if yy < 0 or yy >= h:
                        continue
                    row = yy * w
                    for ox in range(-rad, rad + 1):
                        xx = sx + ox
                        if xx < 0 or xx >= w:
                            continue
                        a = math.exp(-(ox * ox + oy * oy) / max(0.8, size)) * glow * 0.7
                        idx = row + xx
                        R[idx] = _lerp(R[idx], col[0], a)
                        G[idx] = _lerp(G[idx], col[1], a)
                        B[idx] = _lerp(B[idx], col[2], a)

    # post: vignette + grain (single pass)
    vig = 0.0; grain = 0.0
    for t in ops:
        if t[0].lower() == "vignette":
            vig = _num(t, 1)
        elif t[0].lower() == "grain":
            grain = _num(t, 1)
    cx, cy = w / 2, h / 2
    maxd = math.hypot(cx, cy)
    out = bytearray(w * h * 3)
    for y in range(h):
        base = y * w
        for x in range(w):
            idx = base + x
            r, g, b = R[idx], G[idx], B[idx]
            if vig > 0:
                d = math.hypot(x - cx, y - cy) / maxd
                f = 1.0 - vig * (d ** 2)
                r *= f; g *= f; b *= f
            if grain > 0:
                gn = (_h2(x, y, seed + 7) - 0.5) * 255 * grain
                r += gn; g += gn; b += gn
            o = idx * 3
            out[o] = _clamp8(r); out[o + 1] = _clamp8(g); out[o + 2] = _clamp8(b)

    png = _png(w, h, out)
    b64 = base64.b64encode(png).decode()
    return {"kind": "scene", "name": scene["name"], "w": w, "h": h,
            "png_b64": b64, "mime": "image/png"}


# ── extract scene blocks from VokkScript ────────────────────────────────────
def extract_scenes(source: str) -> List[Dict[str, str]]:
    blocks, n = [], len(source)
    for m in re.finditer(r"\bscene\s+([A-Za-z_]\w*)\s*\{", source, re.M):
        name = m.group(1)
        depth, j = 1, m.end()
        while j < n and depth:
            depth += (source[j] == "{") - (source[j] == "}")
            j += 1
        blocks.append({"name": name, "body": source[m.end():j - 1]})
    return blocks


def run_scenes(source: str) -> List[Dict[str, Any]]:
    out = []
    for b in extract_scenes(source):
        try:
            out.append(render_scene(parse_scene(b["name"], b["body"])))
        except Exception as e:
            out.append({"kind": "error", "name": b["name"], "error": str(e)})
    return out


if __name__ == "__main__":
    demo = '''
    scene Dawn {
        size 480 360
        sky #1a2540 #e8a36b
        band 250 360 #2a2233 soft 30
        sun 360 110 46 #fff2c4 intensity 1.6
        haze 150 360 0.5
        fog 0.18
        vignette 0.35
        grain 0.05
    }
    '''
    import time
    t0 = time.time()
    arts = run_scenes(demo)
    for a in arts:
        if a["kind"] == "scene":
            print(f"scene {a['name']}: {a['w']}x{a['h']}, PNG {len(a['png_b64'])} b64 chars, "
                  f"{round((time.time()-t0)*1000)}ms")
            open(f"/tmp/vokk_{a['name']}.png", "wb").write(base64.b64decode(a["png_b64"]))
            print(f"  wrote /tmp/vokk_{a['name']}.png")
        else:
            print("error:", a)
