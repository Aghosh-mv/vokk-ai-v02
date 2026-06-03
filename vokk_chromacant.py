#!/usr/bin/env python3
"""
vokk_chromacant.py - Chromacant, VOKK's synesthetic image+music language.

Chromacant compiles one behavior into both light and sound:

    wave relationships -> SVG aurora/fractal visuals + Web Audio score

It is deliberately small enough to run with the stdlib, but it keeps the user's
core idea intact: frequency maps to visual height, amplitude to luminance, phase
to horizontal movement/pan, and harmonics to texture/timbre.
"""

import math
import re
from typing import Any, Dict, List, Optional, Tuple


def _strip_comments(source: str) -> str:
    return re.sub(r"//.*", "", source)


def _num(value: str, env: Dict[str, float], default: float = 0.0) -> float:
    value = value.strip()
    value = value.replace("Hz", "").replace("hz", "").replace("°", "")
    value = re.sub(r"\bτ\b", "1", value)
    for name, val in sorted(env.items(), key=lambda p: len(p[0]), reverse=True):
        value = re.sub(rf"\b{re.escape(name)}\b", str(val), value)
        value = value.replace("~" + name, str(val))
    value = value.replace("sin", "math.sin")
    try:
        return float(eval(value, {"__builtins__": {}}, {"math": math}))
    except Exception:
        try:
            return float(value)
        except Exception:
            return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _hsl(h: float, s: float, l: float) -> str:
    return f"hsl({int(h) % 360} {int(_clamp(s, 0, 1) * 100)}% {int(_clamp(l, 0, 1) * 100)}%)"


def _extract_block(source: str, keyword: str, name: Optional[str] = None) -> Optional[str]:
    pat = rf"\b{keyword}\b" + (rf"\s+{name}\b" if name else r"(?:\s+[A-Za-z_]\w*)?") + r"\s*\{"
    m = re.search(pat, source)
    if not m:
        return None
    depth, j = 1, m.end()
    while j < len(source) and depth:
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
        j += 1
    return source[m.end():j - 1]


def _canvas(source: str) -> Tuple[int, int]:
    m = re.search(r"\bCanvas\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", source)
    if not m:
        m = re.search(r"#<u8,\s*4>\s*\[\s*0\s*;\s*(\d+)\s*\*\s*(\d+)\s*\]", source)
    if not m:
        return 960, 540
    return max(240, min(int(m.group(1)), 1920)), max(180, min(int(m.group(2)), 1080))


def _waves(source: str) -> Dict[str, float]:
    env: Dict[str, float] = {}
    for name, expr in re.findall(r"~([A-Za-z_]\w*)\s*=\s*([^;]+);", source):
        env[name] = _num(expr, env, 0.0)
    return env


def _colors(source: str, env: Dict[str, float]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for name, body in re.findall(r"#([A-Za-z_]\w*)\s*=\s*\[([\s\S]*?)\]\s*;", source):
        color = {"hue": 180.0, "sat": 0.85, "lum": 0.65}
        for key in ("hue", "sat", "lum"):
            m = re.search(rf"\b{key}\s*:\s*([^,\]\n]+)", body)
            if m:
                val = _num(m.group(1), env, color[key])
                if key == "lum":
                    val = abs(val)
                color[key] = val
        out[name] = color
    if not out:
        out["Aurora_Green"] = {"hue": 135, "sat": 0.9, "lum": 0.68}
        out["Aurora_Purple"] = {"hue": 282, "sat": 0.9, "lum": 0.62}
    return out


def _first_color_pair(colors: Dict[str, Dict[str, float]]) -> Tuple[Dict[str, float], Dict[str, float]]:
    vals = list(colors.values())
    return vals[0], vals[1] if len(vals) > 1 else {"hue": vals[0]["hue"] + 90, "sat": vals[0]["sat"], "lum": vals[0]["lum"] * 0.85}


def _wave_path(w: int, h: int, amp: float, phase: float, y_mid: float, density: int = 96) -> str:
    pts = []
    for i in range(density + 1):
        x = (w * i) / density
        y = y_mid + math.sin(i * 0.22 + phase + x * 0.008) * amp
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _svg(source: str, env: Dict[str, float], colors: Dict[str, Dict[str, float]]) -> str:
    w, h = _canvas(source)
    advanced = _advanced_profile(source)
    base = max(36.0, env.get("base", 55.0))
    shimmer = max(base, env.get("shimmer", base * 16))
    pulse = abs(math.sin(env.get("pulse", 0.5) * math.pi)) or 0.72
    pan = math.sin(env.get("pan", 0.25) * math.pi)
    c1, c2 = _first_color_pair(colors)
    col1 = _hsl(c1["hue"], c1["sat"], max(c1["lum"], 0.35))
    col2 = _hsl(c2["hue"], c2["sat"], max(c2["lum"], 0.3))
    y_mid = h * (0.48 - pan * 0.05)
    amp = h * 0.11 * (0.65 + pulse)
    width = max(10, min(80, int(28 + pulse * 34)))
    paths = []
    for i in range(5):
        decay = 0.62 ** i
        shift = i * w * 0.045
        path = _wave_path(w, h, amp * decay, phase=i * 0.55, y_mid=y_mid + i * 18)
        paths.append(
            f'<polyline points="{path}" transform="translate({shift:.1f},0)" fill="none" '
            f'stroke="url(#aurora)" stroke-width="{max(4, width * decay):.1f}" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity="{0.82 * decay:.3f}" filter="url(#soft)"/>'
        )
    stars = []
    for i in range(46):
        x = (i * 173) % w
        y = (i * 97) % max(1, int(h * 0.42))
        r = 0.7 + ((i * 19) % 9) / 10
        stars.append(f'<circle cx="{x}" cy="{y}" r="{r:.1f}" fill="#f7fbff" opacity="{0.22 + (i % 5) * 0.08:.2f}"/>')
    if advanced == "abyssal":
        return _advanced_abyssal_svg(w, h, source)
    if advanced == "crystal":
        return _advanced_crystal_svg(w, h, source)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        '<defs>'
        '<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#07111f"/><stop offset="62%" stop-color="#10263b"/>'
        '<stop offset="100%" stop-color="#05070d"/></linearGradient>'
        f'<linearGradient id="aurora" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="{col1}"/>'
        f'<stop offset="48%" stop-color="#dfffe9"/><stop offset="100%" stop-color="{col2}"/></linearGradient>'
        '<filter id="soft" x="-10%" y="-40%" width="120%" height="180%"><feGaussianBlur stdDeviation="5"/></filter>'
        '<radialGradient id="bloom"><stop offset="0%" stop-color="#dfffe9" stop-opacity=".44"/>'
        '<stop offset="100%" stop-color="#dfffe9" stop-opacity="0"/></radialGradient>'
        '</defs>'
        f'<rect width="{w}" height="{h}" fill="url(#sky)"/>'
        + "".join(stars)
        + f'<ellipse cx="{w * (0.5 + pan * 0.18):.1f}" cy="{h * 0.5:.1f}" rx="{w * 0.42:.1f}" ry="{h * 0.24:.1f}" fill="url(#bloom)"/>'
        + "".join(paths)
        + f'<rect y="{h * 0.74:.1f}" width="{w}" height="{h * 0.26:.1f}" fill="#05070b" opacity=".76"/>'
        + f'<text x="{w - 24}" y="{h - 22}" text-anchor="end" font-size="14" fill="#dfffe9" opacity=".62">Chromacant: {int(base)}Hz -> light + sound</text>'
        '</svg>'
    )


def _score(source: str, env: Dict[str, float]) -> List[Dict[str, Any]]:
    advanced = _advanced_profile(source)
    if advanced:
        return _advanced_score(source, advanced)
    base = max(36.0, env.get("base", 55.0))
    shimmer = max(base, env.get("shimmer", base * 16))
    pulse = abs(math.sin(env.get("pulse", 0.5) * math.pi)) or 0.72
    pan = math.sin(env.get("pan", 0.25) * math.pi)
    echo = re.search(r"∞\s*\(\s*(\d+)\s*,\s*delay\s*:\s*([\d.]+)s\s*,\s*decay\s*:\s*([\d.]+)", source)
    repeats, decay = (4, 0.6)
    if echo:
        repeats, decay = int(echo.group(1)), float(echo.group(3))
    score: List[Dict[str, Any]] = []
    scale = [1.0, 9 / 8, 5 / 4, 3 / 2, 5 / 4, 9 / 8]
    for i in range(12):
        vol = round(0.18 + 0.32 * (0.5 + 0.5 * math.sin(i * 0.7)) * pulse, 3)
        score.append({"freq": round(base * scale[i % len(scale)], 3), "dur": 0.42, "wave": "sine", "gain": vol, "pan": round(pan, 3)})
        score.append({"freq": round(shimmer * (1 + (i % 3) * 0.005), 3), "dur": 0.42, "wave": "triangle", "gain": round(vol * 0.34, 3), "pan": round(-pan * 0.65, 3)})
    for i in range(1, repeats + 1):
        score.append({"freq": round(base * 2, 3), "dur": 0.28, "wave": "sine", "gain": round(0.2 * (decay ** i), 3), "pan": round(_clamp(-0.7 + i * 0.35, -1, 1), 3)})
    return score


def _fallback_source() -> str:
    return """// Chromacant fallback: Auroral Drone
~base = 55Hz;
~shimmer = base * 16;
~pulse = sin(τ * 0.5Hz);
~pan = sin(τ * 0.25Hz);
#Aurora_Green = [ hue: 120°, sat: 1.0, lum: ~pulse * 0.8 ];
#Aurora_Purple = [ hue: 280°, sat: 0.9, lum: ~pulse * 0.6 ];
Canvas(960, 540);
Stage(Stereo);
render Sky(0 -> τ) {
  ~pan ⟐ X_pos;
  ~pulse ⟐ Y_pos;
  Nexus Aurora_Nexus {
    Visual: Path(Y: 270 + sin(τ * 2 + X_pos * 0.01) * 100 * pulse, Fill: #Aurora_Green ⊕ #Aurora_Purple, Width: 50 * pulse);
    Audio: Synth(Osc: Sine(base) ⊕ Triangle(shimmer * pulse), Vol: pulse * 0.8, Pan: pan);
  }
  ∞(4, delay: 0.4s, decay: 0.6) { Aurora_Nexus ↹ (X_pos + 100, Lum * 0.6, Vol * 0.6); }
}"""


def _advanced_profile(source: str) -> Optional[str]:
    s = source.lower()
    if "abyssal_chrysalis" in s or "chrysalis_sdf" in s or "caustic_estimator" in s:
        return "abyssal"
    if "hypercrystal" in s or "dac_port" in s or "visual_buf" in s:
        return "crystal"
    return None


def _advanced_abyssal_svg(w: int, h: int, source: str) -> str:
    tentacles = []
    cx, cy = w * 0.52, h * 0.42
    for i in range(14):
        ang = (i / 14) * math.tau
        x0 = cx + math.cos(ang) * w * 0.09
        y0 = cy + math.sin(ang) * h * 0.04
        x1 = cx + math.cos(ang + 0.7) * w * 0.22
        y1 = cy + h * 0.22 + (i % 4) * 10
        tentacles.append(
            f'<path d="M{x0:.1f},{y0:.1f} C{x0 + 40:.1f},{y0 + 70:.1f} {x1 - 30:.1f},{y1 - 45:.1f} {x1:.1f},{y1:.1f}" '
            'fill="none" stroke="url(#bio)" stroke-width="5" opacity=".58" filter="url(#watery)"/>'
        )
    rays = []
    for i in range(9):
        x = i * w / 8
        rays.append(f'<path d="M{x:.1f},0 L{x + w * .12:.1f},{h}" stroke="#bffcff" stroke-width="{w*.035:.1f}" opacity=".045"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        '<defs><linearGradient id="abyss" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#052c44"/><stop offset="62%" stop-color="#071827"/><stop offset="100%" stop-color="#020509"/></linearGradient>'
        '<radialGradient id="bell"><stop offset="0%" stop-color="#cfffee" stop-opacity=".86"/><stop offset="58%" stop-color="#3df5a6" stop-opacity=".38"/><stop offset="100%" stop-color="#2d8cff" stop-opacity=".04"/></radialGradient>'
        '<linearGradient id="bio" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ccfff2"/><stop offset="100%" stop-color="#34d6ff"/></linearGradient>'
        '<filter id="watery" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="3"/></filter></defs>'
        f'<rect width="{w}" height="{h}" fill="url(#abyss)"/>'
        + "".join(rays)
        + f'<ellipse cx="{w*.5:.1f}" cy="{h*.78:.1f}" rx="{w*.48:.1f}" ry="{h*.12:.1f}" fill="#020405" opacity=".8"/>'
        + f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{w*.15:.1f}" ry="{h*.18:.1f}" fill="url(#bell)" filter="url(#watery)"/>'
        + "".join(tentacles)
        + f'<circle cx="{cx - w*.04:.1f}" cy="{cy - h*.06:.1f}" r="{w*.055:.1f}" fill="#ecfff9" opacity=".5" filter="url(#watery)"/>'
        + f'<text x="18" y="{h-22}" font-family="ui-monospace,monospace" font-size="13" fill="#9eefff" opacity=".72">Spectral SDF + caustic acoustics -> playable synesthesia</text>'
        '</svg>'
    )


def _advanced_crystal_svg(w: int, h: int, source: str) -> str:
    shards = []
    cx, cy = w * 0.5, h * 0.5
    for i in range(28):
        a = i * 2.399
        r1 = min(w, h) * (0.08 + (i % 7) * 0.018)
        r2 = min(w, h) * (0.18 + (i % 5) * 0.028)
        x1, y1 = cx + math.cos(a) * r1, cy + math.sin(a) * r1
        x2, y2 = cx + math.cos(a + 0.18) * r2, cy + math.sin(a + 0.18) * r2
        x3, y3 = cx + math.cos(a - 0.22) * r2 * .74, cy + math.sin(a - 0.22) * r2 * .74
        hue = (190 + i * 13) % 360
        shards.append(f'<polygon points="{x1:.1f},{y1:.1f} {x2:.1f},{y2:.1f} {x3:.1f},{y3:.1f}" fill="hsl({hue} 90% 58%)" opacity=".48" stroke="#eaffff" stroke-opacity=".22"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        '<defs><radialGradient id="void"><stop offset="0%" stop-color="#18243e"/><stop offset="100%" stop-color="#030407"/></radialGradient>'
        '<filter id="glitch"><feGaussianBlur stdDeviation="1.4"/></filter></defs>'
        f'<rect width="{w}" height="{h}" fill="url(#void)"/>'
        + "".join(shards)
        + f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{min(w,h)*.1:.1f}" fill="#e6ffff" opacity=".72" filter="url(#glitch)"/>'
        + f'<text x="18" y="{h-22}" font-family="ui-monospace,monospace" font-size="13" fill="#d8ffff" opacity=".72">HyperCrystal: framebuffer memory drives bitfolded audio</text>'
        '</svg>'
    )


def _advanced_score(source: str, profile: str) -> List[Dict[str, Any]]:
    score: List[Dict[str, Any]] = []
    if profile == "abyssal":
        freqs = [55, 82.5, 110, 220, 440, 800, 1200]
        for i in range(36):
            f = freqs[i % len(freqs)] * (1 + math.sin(i * .31) * .015)
            score.append({"freq": round(f, 3), "dur": 0.34, "wave": "sine" if i % 3 else "triangle",
                          "gain": round(0.08 + (i % 5) * 0.025, 3), "pan": round(math.sin(i * .45) * .8, 3)})
    else:
        for i in range(44):
            folded = 110 + ((i * 0x4A2B) & 0x3FF) / 2.8
            score.append({"freq": round(folded, 3), "dur": 0.12 + (i % 4) * 0.035,
                          "wave": "sawtooth" if i % 2 else "square", "gain": 0.055,
                          "pan": round(-1 + 2 * ((i % 9) / 8), 3)})
    return score


def run_chromacant(source: str) -> Dict[str, Any]:
    src = _strip_comments(source or "").strip()
    if not _advanced_profile(src) and ("Canvas(" not in src or "Nexus" not in src):
        src = _fallback_source()
    env = _waves(src)
    colors = _colors(src, env)
    return {
        "kind": "chromacant",
        "name": "Chromacant",
        "svg": _svg(src, env, colors),
        "score": _score(src, env),
        "source": src,
        "waves": env,
        "colors": colors,
    }


if __name__ == "__main__":
    art = run_chromacant(_fallback_source())
    print("svg", len(art["svg"]), "score", len(art["score"]))
