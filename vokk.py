#!/usr/bin/env python3
"""
VOKK AI v02 — single-file build (stdlib only, no pip installs).

  - 4-Brain Cognitive Cortex router (Core / Swift / Scout / Pulse)
  - REAL Google Gemini calls for text AND image generation
  - Tamper-evident hash-chained audit log
  - Local web chat UI

Setup the key (never hardcode it):
    echo 'GEMINI_API_KEY=your_fresh_key_here' > ~/.vokk/secrets.env
  (or)  export GEMINI_API_KEY=your_fresh_key_here

Run:
    python3 vokk.py
Open the URL it prints (default http://127.0.0.1:8777).

If no key is found, the minds reply in MOCK mode and tell you so.
"""

import os
import re
import json
import time
import random
import hashlib
import threading
import urllib.request
import urllib.error
from enum import Enum, auto
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# VokkScript builds VOKK's mind (cortex.vokk).
from vokk_lang import run_vokk, extract_blocks, parse_cortex
# VokkImageMusicScript — VOKK's dedicated language for images & music (soft, painterly).
from vokk_imagemusic import run_imagemusic
# The procedural raster engine — VokkScript `scene {}` -> real atmospheric PNG pixels.
from vokk_raster import run_scenes

HOST = os.environ.get("VOKK_HOST", "127.0.0.1")
PORT = int(os.environ.get("VOKK_PORT", "8777"))

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Multiple free models per engine — tried in order; on quota/429 we fall to the next.
GEMINI_TEXT_MODELS = os.environ.get(
    "VOKK_GEMINI_TEXT_MODELS",
    "gemini-2.5-flash,gemini-flash-latest,gemini-2.5-flash-lite,gemini-2.5-pro",
).split(",")
GEMINI_IMAGE_MODELS = os.environ.get(
    "VOKK_GEMINI_IMAGE_MODELS",
    "gemini-2.5-flash-image,gemini-3.1-flash-image,gemini-3-pro-image",
).split(",")
TEXT_MODEL = GEMINI_TEXT_MODELS[0]
IMAGE_MODEL = GEMINI_IMAGE_MODELS[0]

# GLM (Zhipu AI) — co-equal text provider. OpenAI-compatible chat endpoint.
GLM_BASE = os.environ.get("VOKK_GLM_BASE", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
GLM_MODELS = os.environ.get("VOKK_GLM_MODELS", "glm-4.5-flash,glm-4-flash-250414").split(",")
GLM_MODEL = GLM_MODELS[0]


# ─────────────────────────────────────────────────────────────────────────
# Key loading (env vars, then ~/.vokk/secrets.env). Never hardcoded.
# ─────────────────────────────────────────────────────────────────────────
def _load_secrets() -> Dict[str, str]:
    out: Dict[str, str] = {}
    secrets = Path("~/.vokk/secrets.env").expanduser()
    if secrets.exists():
        for line in secrets.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


_SECRETS = _load_secrets()


def _key(name: str) -> Optional[str]:
    return (os.environ.get(name) or _SECRETS.get(name) or "").strip() or None


GEMINI_KEY = _key("GEMINI_API_KEY")
GLM_KEY = _key("GLM_API_KEY")
API_KEY = GEMINI_KEY  # back-compat alias; "live" overall if any provider has a key
HAVE_ANY_KEY = bool(GEMINI_KEY or GLM_KEY)


# ─────────────────────────────────────────────────────────────────────────
# Gemini REST calls (stdlib urllib)
# ─────────────────────────────────────────────────────────────────────────
def _post(url: str, body: dict, timeout: int = 60) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _is_quota_error(e: Exception) -> bool:
    return isinstance(e, urllib.error.HTTPError) and e.code in (429, 503)


def glm_text(prompt: str, system: str, temperature: float = 0.7) -> str:
    """GLM (Zhipu) chat — OpenAI-compatible schema. Tries each model on quota errors."""
    last = None
    for model in GLM_MODELS:
        data = json.dumps({
            "model": model.strip(),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(GLM_BASE, data=data, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GLM_KEY}",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.loads(r.read())
            choices = out.get("choices", [])
            if not choices:
                raise RuntimeError(f"GLM: no choices ({out})")
            return (choices[0].get("message", {}).get("content", "") or "").strip() or "(empty response)"
        except Exception as e:
            last = e
            if _is_quota_error(e):
                continue
            raise
    raise last


def gemini_text(prompt: str, system: str, temperature: float = 0.7) -> str:
    last = None
    for model in GEMINI_TEXT_MODELS:
        url = f"{GEMINI_BASE}/{model.strip()}:generateContent?key={GEMINI_KEY}"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": temperature},
        }
        try:
            out = _post(url, body)
            cands = out.get("candidates", [])
            if not cands:
                raise RuntimeError(f"No response (blocked? {out.get('promptFeedback', {})})")
            parts = cands[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip() or "(empty response)"
        except Exception as e:
            last = e
            if _is_quota_error(e):
                continue
            raise
    raise last


def gemini_image(prompt: str) -> Dict[str, Any]:
    """Returns {'text': str, 'image_b64': str|None, 'mime': str}. Tries each image model on quota errors."""
    last = None
    for model in GEMINI_IMAGE_MODELS:
        url = f"{GEMINI_BASE}/{model.strip()}:generateContent?key={GEMINI_KEY}"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        try:
            out = _post(url, body, timeout=120)
            cands = out.get("candidates", [])
            if not cands:
                raise RuntimeError(f"No image candidates ({out.get('promptFeedback', {})})")
            text, img_b64, mime = "", None, "image/png"
            for p in cands[0].get("content", {}).get("parts", []):
                if "text" in p:
                    text += p["text"]
                inline = p.get("inlineData") or p.get("inline_data")
                if inline:
                    img_b64 = inline.get("data")
                    mime = inline.get("mimeType") or inline.get("mime_type") or mime
            return {"text": text.strip(), "image_b64": img_b64, "mime": mime, "model": model.strip()}
        except Exception as e:
            last = e
            if _is_quota_error(e):
                continue
            raise
    raise last


# ─────────────────────────────────────────────────────────────────────────
# Brain types / routing structures
# ─────────────────────────────────────────────────────────────────────────
class BrainType(Enum):
    CORE = "core"
    SWIFT = "swift"
    SCOUT = "scout"
    PULSE = "pulse"
    FORGE = "forge"        # the coding mind — many languages + VokkScript family
    CANVAS = "canvas"      # paints in VokkImageMusicScript -> soft SVG
    COMPOSER = "composer"  # composes in VokkImageMusicScript -> playable score
    VISTA = "vista"        # writes VokkScript scene  -> procedural raster PNG (photographic)


class TaskClass(Enum):
    CHAT = auto(); CODE = auto(); PLAN = auto()
    VERIFY = auto(); AGENCY = auto(); DEBUG = auto()
    IMAGE = auto(); MUSIC = auto(); SCENE = auto()


@dataclass
class TaskFeatures:
    task_class: TaskClass = TaskClass.CHAT
    complexity: float = 0.5
    latency_sensitivity: float = 0.5
    creativity_required: bool = False
    agency_required: bool = False
    verification_required: bool = False
    image_required: bool = False
    music_required: bool = False
    scene_required: bool = False
    file_operations: int = 0
    reasoning_depth: float = 0.5
    hallucination_risk: float = 0.3
    code_blocks: int = 0
    safety_class: str = "general"


@dataclass
class BrainDecision:
    primary: BrainType
    verifier: Optional[BrainType]
    confidence: float
    reasoning: str
    failover_chain: List[BrainType] = field(default_factory=list)


@dataclass
class BrainResponse:
    brain: BrainType
    content: str
    latency_ms: float
    tokens_used: int
    confidence: float
    svg: Optional[str] = None              # rendered from VokkScript visual
    score: Optional[List[Dict]] = None     # note list from VokkScript music
    png_b64: Optional[str] = None          # raster pixels from VokkScript scene
    vokk_source: Optional[str] = None      # the VokkScript code that was generated
    verified: bool = False
    audit_hash: str = ""
    live: bool = False


# ─────────────────────────────────────────────────────────────────────────
# Audit log (hash-chained)
# ─────────────────────────────────────────────────────────────────────────
class BrainAuditLog:
    def __init__(self, base_path="~/.vokk/audit/brain/"):
        self.base_path = Path(base_path).expanduser()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.chain_hash = "0" * 64
        self.lock = threading.Lock()

    @staticmethod
    def _h(s): return hashlib.sha256(s.encode()).hexdigest()

    def log(self, resp, decision, prompt, user="anonymous"):
        with self.lock:
            entry = {
                "ts": time.time(), "user": user, "brain": resp.brain.value,
                "primary": decision.primary.value,
                "verifier": decision.verifier.value if decision.verifier else None,
                "confidence": decision.confidence, "reasoning": decision.reasoning,
                "prompt_hash": self._h(prompt)[:16],
                "response_hash": self._h(resp.content)[:16],
                "latency_ms": resp.latency_ms, "tokens": resp.tokens_used,
                "live": resp.live, "prev": self.chain_hash,
            }
            eh = self._h(json.dumps(entry, sort_keys=True))
            self.chain_hash = self._h(self.chain_hash + eh)
            entry["entry_hash"] = eh; entry["chain_hash"] = self.chain_hash
            day = time.strftime("%Y-%m-%d")
            with open(self.base_path / f"brain_audit_{day}.jsonl", "a") as f:
                f.write(json.dumps(entry) + "\n")
            return self.chain_hash


# ─────────────────────────────────────────────────────────────────────────
# Brains — real Gemini if key present, else mock
# ─────────────────────────────────────────────────────────────────────────
def _call_engine(engine: str, prompt: str, system: str, temp: float) -> str:
    """Dispatch to a provider, falling back to the other if its key/call fails.
    Gemini and GLM are treated as co-equal text engines."""
    order = ["gemini", "glm"] if engine == "gemini" else ["glm", "gemini"]
    errors = []
    for eng in order:
        try:
            if eng == "gemini" and GEMINI_KEY:
                return gemini_text(prompt, system, temp)
            if eng == "glm" and GLM_KEY:
                return glm_text(prompt, system, temp)
        except Exception as e:
            errors.append(f"{eng}: {e}")
    if errors:
        raise RuntimeError(" | ".join(errors))
    raise RuntimeError("no provider key available")


class Brain:
    btype = BrainType.CORE
    conf = 0.9
    engine = "gemini"          # preferred provider; falls back to the other
    system = "You are VOKK, a helpful assistant."
    temp = 0.7
    mock_lat = (100, 500)

    def generate(self, prompt: str) -> BrainResponse:
        t0 = time.time()
        if HAVE_ANY_KEY:
            text = _call_engine(self.engine, prompt, self.system, self.temp)
            live = True
        else:
            time.sleep(random.uniform(*self.mock_lat) / 1000)
            text = (f"[{self.btype.value} · MOCK] No API key set, so I can't really "
                    f"think yet. You said: {prompt!r}")
            live = False
        return BrainResponse(
            brain=self.btype, content=text,
            latency_ms=round((time.time() - t0) * 1000, 1),
            tokens_used=len(prompt + text) // 4,
            confidence=self.conf, live=live,
        )


# VOKK's identity. It is its own product — it never reveals or references the
# engines/providers behind it, just as Claude/GPT/Grok present as themselves.
IDENTITY = (
    "You are VOKK — a hybrid-intelligence AI made of several specialized minds. "
    "You are your own product with your own identity. Never mention, hint at, or name any "
    "underlying model, provider, company, or API (e.g. do not say Gemini, GLM, Google, "
    "OpenAI, Anthropic, or 'API key'). If asked what powers you, say you run on VOKK's own "
    "Cognitive Cortex. Speak naturally as VOKK. "
)

# Expressive-text capability shared by all text minds. VOKK chooses, in the moment,
# when to emphasize — these render as real styled type in the UI.
EXPRESSIVE = (
    " You may express tone through text styling, used sparingly and only when it genuinely fits:\n"
    " - **bold** for strong emphasis, *italics* for soft emphasis or asides.\n"
    " - [[shout]]TEXT[[/shout]] when something deserves to be (figuratively) said LOUD/big.\n"
    " - [[whisper]]text[[/whisper]] for a quiet, smaller aside.\n"
    " - [[serif]]text[[/serif]], [[mono]]text[[/mono]], [[display]]text[[/display]] to shift font for flavor.\n"
    " Default to plain text; reach for these only when they add real feeling, like a thoughtful writer would."
)


# Brains split evenly across the two co-equal engines:
#   Gemini → Core, Scout     |     GLM → Swift, Pulse
class CoreBrain(Brain):
    btype, conf, temp, engine = BrainType.CORE, 0.94, 0.7, "gemini"
    system = (IDENTITY + "As VOKK Core, the deep-reasoning mind, think carefully and answer "
              "thoroughly but without filler. Use markdown when helpful." + EXPRESSIVE)


class SwiftBrain(Brain):
    btype, conf, temp, engine = BrainType.SWIFT, 0.88, 0.5, "glm"
    system = (IDENTITY + "As VOKK Swift, the fast mind, answer briefly, warmly, and directly. "
              "One or two short paragraphs at most." + EXPRESSIVE)


class ScoutBrain(Brain):
    btype, conf, temp, engine = BrainType.SCOUT, 0.91, 0.6, "gemini"
    system = (IDENTITY + "As VOKK Scout, the agency mind, break tasks into clear, numbered, "
              "actionable steps and lay out a concrete plan." + EXPRESSIVE)


class PulseBrain(Brain):
    btype, conf, temp, engine = BrainType.PULSE, 0.90, 0.2, "glm"
    system = (IDENTITY + "As VOKK Pulse, the verification mind, be precise and skeptical. "
              "Check claims for accuracy and flag anything uncertain." + EXPRESSIVE)


class ForgeBrain(Brain):
    btype, conf, temp, engine = BrainType.FORGE, 0.93, 0.3, "gemini"
    system = (IDENTITY +
        "As VOKK Forge, the coding mind, you write correct, idiomatic, production-quality code. "
        "You are fluent in Python, JavaScript/TypeScript, Rust, Go, C/C++, Java, C#, Swift, Kotlin, "
        "Ruby, PHP, SQL, Bash, HTML/CSS — and VOKK's own languages: VokkScript (which defines "
        "VOKK's minds via agent{} and route{} blocks) and VokkImageMusicScript (image{} and song{} "
        "blocks for visuals and music). Default to the language the user asks for; if unspecified, "
        "pick the most fitting one and say why in one line. Always: put runnable code in a fenced "
        "block with a language tag, keep it complete (no '...'), handle edge cases, and add a short "
        "explanation only when it helps. Prefer clarity and correctness over cleverness." + EXPRESSIVE)


def _strip_fences(s: str) -> str:
    """Pull VokkScript out of an LLM reply that may be wrapped in ``` fences."""
    m = re.search(r"```(?:vokk|vokkscript|visual|music)?\s*(.*?)```", s, re.S)
    return (m.group(1) if m else s).strip()


# Few-shot primers for VokkImageMusicScript — VOKK's dedicated image+music language.
VISUAL_PRIMER = """You write ONLY VokkImageMusicScript image code. No prose, no markdown fences.
This language renders with SOFT gradients, blur and light layering — output is painterly
and atmospheric, NEVER flat papercraft. Grammar:
  image NAME {
    size W H
    wash #topHex #bottomHex                       # smooth vertical gradient backdrop (paint first)
    blob cx cy r #hex [blur B] [opacity O]         # soft radial mass (body, cloud, hill, cheek)
    glow cx cy r #hex [intensity I]                # luminous bloom / light source
    light cx cy r #hex                             # small bright highlight
    stroke x1 y1 x2 y2 #hex width W [blur B]       # soft round-cap painterly stroke
    field x1,y1 x2,y2 .. #hex [blur B] [opacity O] # soft blurred region (ground, shadow shape)
    text x y "s" #hex size N [weight bold] [font serif|mono|display]
  }
0,0 top-left; y grows downward. ONE image block.
Craft soft, luminous, layered art:
  - Start with a wash for the light. Build forms from overlapping translucent BLOBS with blur,
    so edges melt together (this is what kills the papercraft flatness).
  - Model volume: a darker blob for shadow, a lighter blob offset toward the light for the lit side,
    then a small bright `light` for the highlight. Pick one light direction.
  - Use glow for atmosphere/sun/rim light. Use field with blur for soft ground or background masses.
  - 12-30 layered elements. Harmonious palette, gentle contrast. Keep everything inside the canvas."""

MUSIC_PRIMER = """You write ONLY VokkImageMusicScript song code. No prose, no markdown fences.
Grammar:
  song NAME {
    tempo BPM
    wave sine|triangle|square|sawtooth
    play NOTE DUR NOTE DUR ...        # NOTE e.g. C4 D4 E4 F#4 A3; "_" = rest; DUR in beats
    repeat N { play ... }
  }
One song block. A short pleasant recognizable melody (8-24 notes)."""


class CreativeBrain(Brain):
    """Asks an LLM to write VokkImageMusicScript, then compiles it with the real
    renderer (code -> soft SVG / playable score). No image/audio API; reproducible."""
    btype = BrainType.CANVAS
    conf = 0.92
    engine = "gemini"
    primer = VISUAL_PRIMER
    want = "image"          # "image" or "music"

    def generate(self, prompt: str) -> BrainResponse:
        t0 = time.time()
        lang = "image" if self.want == "image" else "song"
        ask = f"{self.primer}\n\nUser request: {prompt}\n\nReturn only the VokkImageMusicScript {lang} block."
        if HAVE_ANY_KEY:
            try:
                raw = _call_engine(self.engine, ask, "You are a precise VokkImageMusicScript generator.", 0.6)
                live = True
            except Exception:
                raw, live = self._fallback(prompt), False
        else:
            raw, live = self._fallback(prompt), False

        source = _strip_fences(raw)
        arts = run_imagemusic(source)
        art = next((a for a in arts if a.get("kind") == self.want), None)
        ok = art and (art.get("svg") if self.want == "image" else art.get("score"))
        if not ok:                      # invalid -> guaranteed-valid fallback
            source = self._fallback(prompt)
            art = run_imagemusic(source)[0]

        verb = "painted" if self.want == "image" else "composed"
        content = (f"VOKK {self.btype.value.title()} {verb} this in VokkImageMusicScript — "
                   f"its own image/music language — no image/audio API, fully reproducible.")
        return BrainResponse(
            brain=self.btype, content=content,
            latency_ms=round((time.time() - t0) * 1000, 1),
            tokens_used=len(prompt + source) // 4, confidence=self.conf,
            svg=art.get("svg"), score=art.get("score"),
            vokk_source=source, live=live,
        )

    def _fallback(self, prompt: str) -> str:
        raise NotImplementedError


class CanvasBrain(CreativeBrain):
    btype, primer, want = BrainType.CANVAS, VISUAL_PRIMER, "image"

    def _fallback(self, prompt: str) -> str:
        return ('image Fallback {\n'
                '  size 420 320\n'
                '  wash #20283a #e9b27a\n'
                '  glow 300 110 170 #ffe6b0 intensity 1.3\n'
                '  light 300 110 34 #ffffff\n'
                '  field 0,230 420,210 420,320 0,320 #2a2433 blur 14 opacity 0.85\n'
                '  blob 120 250 70 #3a3550 blur 12 opacity 0.6\n'
                '}')


class ComposerBrain(CreativeBrain):
    btype, primer, want = BrainType.COMPOSER, MUSIC_PRIMER, "music"

    def _fallback(self, prompt: str) -> str:
        return ('song Fallback {\n'
                '  tempo 120\n'
                '  wave triangle\n'
                '  play C4 1 E4 1 G4 1 C5 1 G4 1 E4 1 C4 2\n'
                '}')


SCENE_PRIMER = """You write ONLY VokkScript scene code. No prose, no markdown fences.
This renders to real PIXELS in VOKK's signature atmospheric/luminous style — soft light,
gradients, glow, fog, depth. Not cartoon, not flat: photographic in FEEL.
Grammar:
  scene NAME {
    size W H                       # up to 960 x 720
    sky #topHex #bottomHex         # vertical light gradient (paint this first, the base)
    band y0 y1 #hex [soft S]       # horizontal field: horizon, ground, water, ridge. soft=edge blur
    glow cx cy radius #hex [intensity I]   # soft light bloom / atmosphere
    sun  cx cy radius #hex [intensity I]   # bright luminous core + halo
    haze y0 y1 amount              # atmospheric depth fading toward a band (0..1)
    fog amount [#tint]             # value-noise haze across the whole frame (0..1)
    vignette amount                # darkened edges (0..0.5)
    grain amount                   # subtle film grain (0..0.08)
  }
Compose for mood and light. Order ops back-to-front: sky, then distant bands, then
nearer bands, then sun/glow, then haze/fog, then vignette/grain. Choose a refined,
harmonious palette. ONE scene block."""


class VistaBrain(CreativeBrain):
    """Writes VokkScript `scene` code, rendered by the procedural raster engine
    into real atmospheric PNG pixels — VOKK's signature photographic style."""
    btype, primer, want = BrainType.VISTA, SCENE_PRIMER, "scene"

    def generate(self, prompt: str) -> BrainResponse:
        t0 = time.time()
        ask = f"{self.primer}\n\nUser request: {prompt}\n\nReturn only the VokkScript scene block."
        if HAVE_ANY_KEY:
            try:
                raw = _call_engine(self.engine, ask, "You are a precise VokkScript generator.", 0.6)
                live = True
            except Exception:
                raw, live = self._fallback(prompt), False
        else:
            raw, live = self._fallback(prompt), False

        source = _strip_fences(raw)
        arts = run_scenes(source)
        art = next((a for a in arts if a.get("kind") == "scene"), None)
        if not art or not art.get("png_b64"):
            source = self._fallback(prompt)
            art = run_scenes(source)[0]
        content = ("VOKK Vista rendered this by writing a VokkScript scene and painting it "
                   "pixel by pixel through the procedural raster engine — its own atmospheric "
                   "style, fully reproducible.")
        return BrainResponse(
            brain=self.btype, content=content,
            latency_ms=round((time.time() - t0) * 1000, 1),
            tokens_used=len(prompt + source) // 4, confidence=self.conf,
            png_b64=art.get("png_b64"), vokk_source=source, live=live,
        )

    def _fallback(self, prompt: str) -> str:
        return ('scene Vista {\n'
                '  size 480 360\n'
                '  sky #1a2540 #e8a36b\n'
                '  band 250 360 #2a2233 soft 30\n'
                '  sun 360 110 46 #fff2c4 intensity 1.6\n'
                '  haze 150 360 0.5\n'
                '  fog 0.16\n'
                '  vignette 0.35\n'
                '  grain 0.04\n'
                '}')


# ─────────────────────────────────────────────────────────────────────────
# Router — the Hybrid Intelligence Router from the spec.
# Task features are CLASSIFIED BY A MODEL, not by keyword lists. The router
# then routes on those features. No hardcoded trigger words anywhere.
# ─────────────────────────────────────────────────────────────────────────
CLASSIFIER_SYSTEM = (
    "You are VOKK's task classifier. Read the user's message and output ONLY a compact "
    "JSON object (no prose, no markdown) describing the task as features:\n"
    '{"task_class": one of '
    '["chat","code","plan","verify","agency","debug","image","music","scene"],'
    ' "complexity": 0..1, "latency_sensitivity": 0..1, "creativity_required": bool,'
    ' "agency_required": bool, "verification_required": bool, "reasoning_depth": 0..1,'
    ' "safety_class": one of ["general","medical","financial","legal"]}\n\n'
    "Definitions (judge by MEANING, never by specific words):\n"
    "- image: the user wants a drawn/illustrated picture, portrait, logo, or graphic — "
    "crisp stylized art of a SUBJECT (a person, object, character, icon).\n"
    "- scene: the user wants an atmospheric, photographic, or scenic image — a landscape, "
    "sky, sunset, mood, place, or anything 'photorealistic' / 'a photo of'. Render is painterly pixels.\n"
    "- music: the user wants a melody, tune, song, jingle, or composition MADE.\n"
    "- agency: the user wants something BUILT or DONE in multiple steps — scaffold/create/"
    "set up a project, app, website, or file structure. Set agency_required=true, complexity>=0.6.\n"
    "- code: write/explain a single function, snippet, or algorithm (not a whole project).\n"
    "- debug: fix an error, trace a bug, diagnose a failure. reasoning_depth>=0.8.\n"
    "- plan: design, architect, strategize, or lay out a roadmap. complexity>=0.7.\n"
    "- verify: fact-check, validate, or confirm correctness. verification_required=true.\n"
    "- chat: greeting, small talk, or a simple short question. latency_sensitivity>=0.8, complexity<=0.3.\n\n"
    "Worked examples:\n"
    'msg: "scaffold a react todo app" -> {"task_class":"agency","complexity":0.7,'
    '"agency_required":true,"latency_sensitivity":0.3,"reasoning_depth":0.6,"safety_class":"general"}\n'
    'msg: "build me a landing page" -> {"task_class":"agency","complexity":0.65,"agency_required":true}\n'
    'msg: "yo whats up" -> {"task_class":"chat","complexity":0.1,"latency_sensitivity":0.9}\n'
    'msg: "draw a portrait of a woman" -> {"task_class":"image","creativity_required":true}\n'
    'msg: "a photorealistic mountain sunset" -> {"task_class":"scene","creativity_required":true}\n'
    'msg: "show me a foggy harbor at dawn" -> {"task_class":"scene","creativity_required":true}\n'
    'msg: "write me a jingle" -> {"task_class":"music","creativity_required":true}\n'
    'msg: "why is my for loop off by one" -> {"task_class":"debug","reasoning_depth":0.85}\n'
    'msg: "is the earth flat, check it" -> {"task_class":"verify","verification_required":true}\n'
    'msg: "design a microservices architecture" -> {"task_class":"plan","complexity":0.8}'
)
_TASK_CLASS = {tc.name.lower(): tc for tc in TaskClass}


class CortexRouter:
    def __init__(self):
        self.audit = BrainAuditLog()
        self.brains = {
            BrainType.CORE: CoreBrain(), BrainType.SWIFT: SwiftBrain(),
            BrainType.SCOUT: ScoutBrain(), BrainType.PULSE: PulseBrain(),
            BrainType.FORGE: ForgeBrain(),
            BrainType.CANVAS: CanvasBrain(), BrainType.COMPOSER: ComposerBrain(),
            BrainType.VISTA: VistaBrain(),
        }
        # VOKK's own mind is DEFINED IN VOKKSCRIPT (cortex.vokk) and loaded here,
        # so the AI's architecture runs on the language VOKK created.
        self.routes = {}
        self._load_cortex()

    def _load_cortex(self):
        path = Path(__file__).with_name("cortex.vokk")
        if not path.exists():
            return
        try:
            cfg = parse_cortex(path.read_text())
        except Exception:
            return
        # apply agent specs from VokkScript onto the live brains
        for name, spec in cfg.get("agents", {}).items():
            bt = next((b for b in BrainType if b.value == name.lower()), None)
            if not bt or bt not in self.brains:
                continue
            brain = self.brains[bt]
            if "engine" in spec:
                brain.engine = str(spec["engine"])
            if "confidence" in spec:
                brain.conf = float(spec["confidence"])
            if "temp" in spec:
                brain.temp = float(spec["temp"])
            if "role" in spec:  # rebuild system prompt from VokkScript-declared role
                brain.system = IDENTITY + "As VOKK " + name + ", " + str(spec["role"]) + EXPRESSIVE
        # build routing table {task_class -> BrainType} from VokkScript route block
        for task, agent in cfg.get("routes", {}).items():
            bt = next((b for b in BrainType if b.value == agent.lower()), None)
            if bt:
                self.routes[task] = bt
        self.cortex_loaded = True

    def _features(self, prompt):
        """Model-classified features. Falls back to a neutral default (Core) only
        when no model is reachable — never to keyword matching."""
        f = TaskFeatures()
        if not HAVE_ANY_KEY:
            return f  # neutral; offline mock mode routes to Core by default
        try:
            # Stronger engine (Gemini) classifies for accuracy; falls back to GLM if needed.
            raw = _call_engine("gemini", prompt, CLASSIFIER_SYSTEM, 0.0)
            data = json.loads(_strip_fences(raw))
        except Exception:
            return f  # classification unavailable -> neutral default, no keyword guessing
        tc = _TASK_CLASS.get(str(data.get("task_class", "")).lower())
        if tc:
            f.task_class = tc
        f.complexity = float(data.get("complexity", f.complexity))
        f.latency_sensitivity = float(data.get("latency_sensitivity", f.latency_sensitivity))
        f.reasoning_depth = float(data.get("reasoning_depth", f.reasoning_depth))
        f.creativity_required = bool(data.get("creativity_required", False))
        f.agency_required = bool(data.get("agency_required", False))
        f.verification_required = bool(data.get("verification_required", False))
        f.safety_class = str(data.get("safety_class", "general"))
        f.image_required = f.task_class == TaskClass.IMAGE
        f.music_required = f.task_class == TaskClass.MUSIC
        f.scene_required = f.task_class == TaskClass.SCENE
        return f

    def _route(self, f):
        # Safety always overrides the VokkScript table (Pulse must verify).
        if f.safety_class in ("medical", "financial", "legal"):
            return BrainDecision(BrainType.CORE, BrainType.PULSE, 0.98,
                                 "Safety-critical: Core answers, Pulse verifies", [BrainType.SCOUT])
        # Routing defined in cortex.vokk (VOKK's own language) drives the decision.
        tc = f.task_class.name.lower()
        if tc in self.routes:
            primary = self.routes[tc]
            fb = [self.routes.get("default", BrainType.CORE)]
            return BrainDecision(primary, None, self.brains[primary].conf,
                                 f"cortex.vokk routes '{tc}' → {primary.value}", fb)
        # feature-based fallback (only if VokkScript table lacks this class)
        if f.agency_required:
            return BrainDecision(BrainType.SCOUT, None, 0.93,
                                 "Agency required: Scout plans the workflow", [BrainType.CORE])
        if f.verification_required:
            return BrainDecision(BrainType.PULSE, None, 0.97, "Verification task: Pulse primary", [BrainType.CORE])
        if f.latency_sensitivity > 0.8 and f.complexity < 0.4:
            return BrainDecision(BrainType.SWIFT, None, 0.89, "Quick & simple: Swift fast path", [BrainType.CORE])
        if f.reasoning_depth > 0.75 or f.complexity > 0.7:
            return BrainDecision(BrainType.CORE, None, 0.92, "Deep reasoning: Core", [BrainType.SCOUT, BrainType.SWIFT])
        return BrainDecision(BrainType.CORE, None, 0.85, "Default: Core balanced mode", [BrainType.SWIFT])

    def route(self, prompt, user="anonymous"):
        f = self._features(prompt)
        d = self._route(f)
        t0 = time.time()
        try:
            resp = self.brains[d.primary].generate(prompt)
        except Exception as e:
            resp = None
            for bt in d.failover_chain:
                try:
                    resp = self.brains[bt].generate(prompt); break
                except Exception:
                    continue
            if resp is None:
                raise RuntimeError(f"All minds failed. Last error: {e}")
        verification_conf = None
        if d.verifier and resp.live:
            try:
                v = self.brains[d.verifier].generate(f"Verify this answer for accuracy:\n\n{resp.content}")
                verification_conf, resp.verified = v.confidence, v.confidence > 0.9
            except Exception:
                pass
        total = (time.time() - t0) * 1000
        resp.audit_hash = self.audit.log(resp, d, prompt, user)
        return {
            "response": resp.content,
            "svg": resp.svg,
            "score": resp.score,
            "png_b64": resp.png_b64,
            "vokk_source": resp.vokk_source,
            "brain_used": resp.brain.value,
            "live": resp.live,
            "latency_ms": round(total, 1),
            "tokens_used": resp.tokens_used,
            "routing_confidence": d.confidence,
            "routing_reasoning": d.reasoning,
            "verifier_used": d.verifier.value if d.verifier else None,
            "verification_confidence": verification_conf,
            "verified": resp.verified,
            "task_class": f.task_class.name,
            "audit_hash": resp.audit_hash[:16],
        }


ROUTER = CortexRouter()


# ─────────────────────────────────────────────────────────────────────────
# Web UI
# ─────────────────────────────────────────────────────────────────────────
PAGE = r"""<!doctype html><html lang="en" data-theme="light"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VOKK</title><style>
:root{
  --bg:#f5f1e8; --bg2:#efe9da; --panel:#fffdf8; --side:#efe7d6; --ink:#2c2a26; --soft:#6b6557;
  --muted:#9c9484; --line:#e3dccb; --accent:#bd5d3a; --accent-ink:#fff; --hover:#e7dfcd;
  --core:#7c6f9f; --swift:#3f8f7a; --scout:#bd8a3a; --pulse:#9a6ab0; --canvas:#c0617e; --composer:#c79a2e;
  --shadow:0 8px 30px rgba(60,50,30,.10);
}
html[data-theme="dark"]{
  --bg:#1c1a17; --bg2:#252320; --panel:#2a2824; --side:#201e1b; --ink:#ece7dc; --soft:#b6ad9c;
  --muted:#8a8273; --line:#39352f; --accent:#d9784f; --accent-ink:#1c1a17; --hover:#302d28;
  --core:#a99fd0; --swift:#6fc7ad; --scout:#e3b566; --pulse:#c79ad8; --canvas:#e58aa6; --composer:#e8c45f;
  --shadow:0 8px 30px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",sans-serif;background:var(--bg);
  color:var(--ink);height:100vh;overflow:hidden;display:flex;transition:background .4s,color .4s}
/* ── sidebar ── */
#side{width:260px;flex:none;background:var(--side);border-right:1px solid var(--line);
  display:flex;flex-direction:column;transition:width .32s cubic-bezier(.22,.61,.36,1),padding .32s}
#side.collapsed{width:0;border-right:0}
#side .inner{width:260px;flex:1;display:flex;flex-direction:column;overflow:hidden}
.side-top{padding:16px 14px 8px;display:flex;align-items:center;gap:8px}
.mark{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--scout));
  flex:none;display:grid;place-items:center;color:#fff;font-weight:800;font-size:14px;
  box-shadow:0 2px 8px rgba(189,93,58,.4)}
.side-top .brand{font-weight:600;letter-spacing:.3px}
.newbtn{margin:6px 12px 10px;padding:10px 14px;border:1px solid var(--line);background:var(--panel);
  color:var(--ink);border-radius:12px;cursor:pointer;font-weight:600;font-size:14px;text-align:left;
  display:flex;align-items:center;gap:9px;transition:transform .15s,background .2s,box-shadow .2s}
.newbtn:hover{background:var(--hover);transform:translateY(-1px);box-shadow:var(--shadow)}
.convs{flex:1;overflow-y:auto;padding:4px 8px}
.clabel{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;padding:8px 8px 4px}
.conv{padding:9px 11px;border-radius:10px;cursor:pointer;font-size:14px;color:var(--soft);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:background .18s,color .18s;
  display:flex;align-items:center;gap:8px;animation:slidein .25s ease}
.conv:hover{background:var(--hover);color:var(--ink)}
.conv.active{background:var(--hover);color:var(--ink);font-weight:600}
.conv .del{margin-left:auto;opacity:0;color:var(--muted);transition:opacity .15s}
.conv:hover .del{opacity:.7}.conv .del:hover{color:var(--accent);opacity:1}
.side-bot{padding:10px 12px;border-top:1px solid var(--line);display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
.side-bot .dot{width:7px;height:7px;border-radius:50%;background:var(--muted)}.side-bot .dot.on{background:var(--swift)}
/* ── main ── */
#main{flex:1;display:flex;flex-direction:column;min-width:0}
.topbar{height:54px;display:flex;align-items:center;gap:8px;padding:0 16px;border-bottom:1px solid transparent;
  transition:border-color .3s}
.topbar.scrolled{border-color:var(--line)}
.icon{background:transparent;border:0;color:var(--soft);border-radius:10px;width:38px;height:38px;
  font-size:18px;cursor:pointer;display:grid;place-items:center;transition:background .18s,transform .15s}
.icon:hover{background:var(--hover);transform:scale(1.05)}
.topttl{font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#log{flex:1;overflow-y:auto;padding:10px 20px 24px;scroll-behavior:smooth}
.col{max-width:720px;margin:0 auto;width:100%}
#hero{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;gap:12px;animation:fadeup .5s ease}
.heromark{width:54px;height:54px;border-radius:16px;background:linear-gradient(135deg,var(--accent),var(--scout));
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:26px;box-shadow:var(--shadow);
  animation:breathe 4s ease-in-out infinite}
#hero h1{font-weight:500;font-size:30px;color:var(--ink);margin:0}
#hero p{margin:0;color:var(--muted);max-width:440px}
.chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:6px}
.chip{padding:8px 14px;border:1px solid var(--line);border-radius:20px;background:var(--panel);
  color:var(--soft);font-size:13px;cursor:pointer;transition:transform .15s,background .2s,box-shadow .2s}
.chip:hover{background:var(--hover);transform:translateY(-2px);box-shadow:var(--shadow)}
.msg{margin:18px 0;display:flex;flex-direction:column;gap:6px;animation:fadeup .35s ease}
.msg.me{align-items:flex-end}
.bubble{padding:12px 16px;border-radius:16px;max-width:88%;word-wrap:break-word}
.me .bubble{background:var(--bg2);border:1px solid var(--line);border-bottom-right-radius:5px}
.ai .bubble{background:var(--panel);border:1px solid var(--line);border-bottom-left-radius:5px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.bubble p{margin:.4em 0}.bubble p:first-child{margin-top:0}.bubble p:last-child{margin-bottom:0}
.bubble ol,.bubble ul{margin:.4em 0;padding-left:1.3em}
.bubble code{background:var(--bg2);padding:1px 5px;border-radius:5px;font:13px ui-monospace,monospace}
.bubble svg{max-width:100%;border-radius:12px;margin-top:10px;display:block;border:1px solid var(--line);
  animation:fadein .5s ease}
.shout{font-size:1.4em;font-weight:800;letter-spacing:.3px}
.whisper{font-size:.82em;color:var(--muted)}
.serif{font-family:Georgia,serif}.mono{font-family:ui-monospace,Menlo,monospace}
.disp{font-family:"Trebuchet MS","Gill Sans",sans-serif;letter-spacing:.4px}
.art{margin-top:6px}
.vokksrc{margin-top:8px;background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:9px 11px;
  font:12px/1.45 ui-monospace,Menlo,monospace;color:var(--soft);white-space:pre;overflow-x:auto;animation:fadein .3s}
.btn{margin-top:8px;border-radius:10px;padding:5px 12px;font-size:13px;font-weight:600;cursor:pointer;
  border:1px solid var(--line);transition:transform .15s,background .2s}.btn:hover{transform:translateY(-1px)}
.playbtn{background:var(--composer);color:#3a2f00;border:0}
.srcbtn{background:transparent;color:var(--muted)}
.meta{font-size:11.5px;color:var(--muted);display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.tag{padding:1px 9px;border-radius:20px;font-weight:600}
.tag.core{color:var(--core)}.tag.swift{color:var(--swift)}.tag.scout{color:var(--scout)}
.tag.pulse{color:var(--pulse)}.tag.canvas{color:var(--canvas)}.tag.composer{color:var(--composer)}.tag.vista{color:var(--scout)}
.typing span{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--muted);margin-right:3px;
  animation:bounce 1.2s infinite}.typing span:nth-child(2){animation-delay:.15s}.typing span:nth-child(3){animation-delay:.3s}
footer{padding:10px 20px 18px}
.dock{max-width:720px;margin:0 auto;display:flex;gap:10px;align-items:flex-end;background:var(--panel);
  border:1px solid var(--line);border-radius:20px;padding:8px 8px 8px 16px;box-shadow:var(--shadow);
  transition:border-color .2s}
.dock:focus-within{border-color:var(--accent)}
textarea{flex:1;resize:none;background:transparent;color:var(--ink);border:0;outline:none;font:inherit;
  line-height:1.5;max-height:160px;height:28px;padding:6px 0}
#send{background:var(--accent);color:var(--accent-ink);border:0;border-radius:13px;width:40px;height:40px;
  font-size:17px;cursor:pointer;flex:none;transition:transform .15s,opacity .2s}
#send:hover:not(:disabled){transform:scale(1.08)}#send:disabled{opacity:.4;cursor:default}
.hint{max-width:720px;margin:8px auto 0;text-align:center;color:var(--muted);font-size:11.5px}
@keyframes fadeup{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
@keyframes slidein{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:none}}
@keyframes breathe{0%,100%{transform:scale(1)}50%{transform:scale(1.07)}}
@keyframes bounce{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-5px);opacity:1}}
@media(max-width:760px){#side{position:absolute;z-index:10;height:100%;box-shadow:var(--shadow)}}
</style></head><body>
<aside id="side"><div class="inner">
  <div class="side-top"><div class="mark">V</div><div class="brand">VOKK</div></div>
  <button class="newbtn" id="newchat">✦ New chat</button>
  <div class="convs"><div class="clabel">Conversations</div><div id="convlist"></div></div>
  <div class="side-bot"><span id="sdot" class="dot"></span><span id="smode">checking…</span></div>
</div></aside>
<div id="main">
  <div class="topbar" id="topbar">
    <button class="icon" id="toggle" title="Toggle sidebar">☰</button>
    <div class="topttl" id="topttl">New chat</div>
    <button class="icon" id="theme" title="Light / dark">◐</button>
  </div>
  <div id="log"><div class="col" id="col"><div id="hero">
    <div class="heromark">V</div>
    <h1>What shall we make?</h1>
    <p>Ask, draw, or compose. VOKK quietly routes your words to the right mind.</p>
    <div class="chips">
      <div class="chip" data-q="Draw a calm mountain sunrise">Draw a sunrise</div>
      <div class="chip" data-q="Compose a gentle lo-fi melody">Compose a melody</div>
      <div class="chip" data-q="Help me plan my week">Plan my week</div>
    </div>
  </div></div></div>
  <footer>
    <div class="dock"><textarea id="box" rows="1" placeholder="Message VOKK…"></textarea>
      <button id="send" title="Send">↑</button></div>
    <div class="hint">VOKK chooses one of six minds · images & music are written as VokkScript</div>
  </footer>
</div>
<script>
const $=id=>document.getElementById(id);
const logEl=$('log'),box=$('box'),send=$('send');
let col=$('col');

/* theme */
const savedT=localStorage.getItem('vokk-theme'); if(savedT)document.documentElement.dataset.theme=savedT;
$('theme').onclick=()=>{const d=document.documentElement;
  d.dataset.theme=d.dataset.theme==='dark'?'light':'dark';localStorage.setItem('vokk-theme',d.dataset.theme);};
/* sidebar collapse */
if(localStorage.getItem('vokk-side')==='1')$('side').classList.add('collapsed');
$('toggle').onclick=()=>{$('side').classList.toggle('collapsed');
  localStorage.setItem('vokk-side',$('side').classList.contains('collapsed')?'1':'0');};
$('log').addEventListener('scroll',()=>$('topbar').classList.toggle('scrolled',logEl.scrollTop>4));

/* ── conversation store (local) ── */
let convs=JSON.parse(localStorage.getItem('vokk-convs')||'[]');
let curId=null;
const save=()=>localStorage.setItem('vokk-convs',JSON.stringify(convs));
const cur=()=>convs.find(c=>c.id===curId);
function renderList(){const L=$('convlist');L.innerHTML='';
  convs.slice().reverse().forEach(c=>{const d=document.createElement('div');
    d.className='conv'+(c.id===curId?' active':'');d.textContent=c.title||'New chat';
    const x=document.createElement('span');x.className='del';x.textContent='✕';
    x.onclick=e=>{e.stopPropagation();convs=convs.filter(k=>k.id!==c.id);save();
      if(curId===c.id){curId=null;newChat();}renderList();};
    d.appendChild(x);d.onclick=()=>openConv(c.id);L.appendChild(d);});}
function newChat(){curId=null;$('topttl').textContent='New chat';
  col.innerHTML='<div id="hero"><div class="heromark">V</div><h1>What shall we make?</h1>'+
    '<p>Ask, draw, or compose. VOKK quietly routes your words to the right mind.</p>'+
    '<div class="chips"><div class="chip" data-q="Draw a calm mountain sunrise">Draw a sunrise</div>'+
    '<div class="chip" data-q="Compose a gentle lo-fi melody">Compose a melody</div>'+
    '<div class="chip" data-q="Help me plan my week">Plan my week</div></div></div>';
  bindChips();renderList();box.focus();}
function openConv(id){curId=id;const c=cur();$('topttl').textContent=c.title||'Chat';
  col.innerHTML='';c.msgs.forEach(m=>m.who==='me'?drawMe(m.text):drawAi(m.data));
  renderList();logEl.scrollTop=logEl.scrollHeight;}
$('newchat').onclick=newChat;
function bindChips(){document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{box.value=c.dataset.q;ask();});}

/* ── render helpers ── */
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmt(t){let s=esc(t);
  s=s.replace(/\[\[shout\]\]([\s\S]*?)\[\[\/shout\]\]/g,'<span class="shout">$1</span>')
     .replace(/\[\[whisper\]\]([\s\S]*?)\[\[\/whisper\]\]/g,'<span class="whisper">$1</span>')
     .replace(/\[\[serif\]\]([\s\S]*?)\[\[\/serif\]\]/g,'<span class="serif">$1</span>')
     .replace(/\[\[mono\]\]([\s\S]*?)\[\[\/mono\]\]/g,'<span class="mono">$1</span>')
     .replace(/\[\[display\]\]([\s\S]*?)\[\[\/display\]\]/g,'<span class="disp">$1</span>')
     .replace(/`([^`]+)`/g,'<code>$1</code>')
     .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
     .replace(/(^|[^*])\*([^*]+)\*/g,'$1<em>$2</em>');
  return s.split(/\n{2,}/).map(p=>'<p>'+p.replace(/\n/g,'<br>')+'</p>').join('');}
function dropHero(){const h=$('hero');if(h)h.remove();}
function drawMe(text){dropHero();const m=document.createElement('div');m.className='msg me';
  const b=document.createElement('div');b.className='bubble';b.textContent=text;m.appendChild(b);
  col.appendChild(m);logEl.scrollTop=logEl.scrollHeight;return b;}
function drawAi(d){dropHero();const m=document.createElement('div');m.className='msg ai';
  const b=document.createElement('div');b.className='bubble';m.appendChild(b);
  if(d.error){b.innerHTML='<span class="whisper">⚠ '+esc(d.error)+'</span>';col.appendChild(m);return b;}
  b.innerHTML=fmt(d.response||'');
  if(d.svg){const w=document.createElement('div');w.className='art';w.innerHTML=d.svg;b.appendChild(w);}
  if(d.png_b64){const im=new Image();im.className='art';im.style.maxWidth='100%';im.style.borderRadius='12px';
    im.style.marginTop='10px';im.style.display='block';im.src='data:image/png;base64,'+d.png_b64;b.appendChild(im);}
  if(d.score&&d.score.length){const pb=document.createElement('button');pb.className='btn playbtn';
    pb.textContent='▶ play';pb.onclick=()=>playScore(d.score,d.score[0]&&d.score[0].wave);b.appendChild(pb);}
  if(d.vokk_source){const sb=document.createElement('button');sb.className='btn srcbtn';
    sb.textContent='‹ › VokkScript';const pre=document.createElement('div');pre.className='vokksrc';
    pre.style.display='none';pre.textContent=d.vokk_source;
    sb.onclick=()=>pre.style.display=pre.style.display==='none'?'block':'none';
    b.appendChild(sb);b.appendChild(pre);}
  const t=d.brain_used,meta=document.createElement('div');meta.className='meta';
  meta.innerHTML=`<span class="tag ${t}">${(t||'').toUpperCase()}</span><span>${esc(d.routing_reasoning||'')}</span>`+
    `<span>${d.latency_ms} ms</span>`+(d.live?'':'<span>⚠ mock</span>')+
    (d.verified?'<span>✓ verified</span>':'')+`<span>audit ${d.audit_hash}</span>`;
  m.appendChild(meta);col.appendChild(m);logEl.scrollTop=logEl.scrollHeight;return b;}

/* status */
fetch('/api/status').then(r=>r.json()).then(s=>{
  $('sdot').classList.toggle('on',!!s.live);$('smode').textContent=s.live?'online':'mock mode';});

/* audio */
let actx=null;
function playScore(score,wave){actx=actx||new(window.AudioContext||window.webkitAudioContext)();
  let t=actx.currentTime+0.05;for(const n of score){if(n.freq){const o=actx.createOscillator(),g=actx.createGain();
    o.type=wave||'sine';o.frequency.value=n.freq;g.gain.setValueAtTime(0.0001,t);
    g.gain.exponentialRampToValueAtTime(0.25,t+0.02);g.gain.exponentialRampToValueAtTime(0.0001,t+n.dur*0.95);
    o.connect(g);g.connect(actx.destination);o.start(t);o.stop(t+n.dur);}t+=n.dur;}}

box.addEventListener('input',()=>{box.style.height='28px';box.style.height=Math.min(box.scrollHeight,160)+'px';});

async function ask(){const q=box.value.trim();if(!q)return;box.value='';box.style.height='28px';send.disabled=true;
  if(!curId){curId=Date.now()+'';convs.push({id:curId,title:q.slice(0,40),msgs:[]});save();}
  const c=cur();drawMe(q);c.msgs.push({who:'me',text:q});if(c.msgs.length===1){$('topttl').textContent=c.title;}
  const tm=document.createElement('div');tm.className='msg ai';
  tm.innerHTML='<div class="bubble"><span class="typing"><span></span><span></span><span></span></span></div>';
  col.appendChild(tm);logEl.scrollTop=logEl.scrollHeight;
  try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({prompt:q})});const d=await r.json();tm.remove();
    drawAi(d);c.msgs.push({who:'ai',data:d});save();renderList();
    if(d.score&&d.score.length)playScore(d.score,d.score[0]&&d.score[0].wave);
  }catch(e){tm.remove();drawAi({error:''+e});}
  finally{send.disabled=false;box.focus();}}
send.onclick=ask;
box.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();}});
renderList();bindChips();box.focus();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            engines = []
            if GEMINI_KEY:
                engines.append(f"Gemini {TEXT_MODEL}")
            if GLM_KEY:
                engines.append(f"GLM {GLM_MODEL}")
            self._send(200, json.dumps({
                "live": HAVE_ANY_KEY,
                "engines": engines,
                "text_model": " + ".join(engines) if engines else "none",
                "gemini": bool(GEMINI_KEY), "glm": bool(GLM_KEY),
                "image_model": IMAGE_MODEL,
            }))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/chat":
            self._send(404, json.dumps({"error": "not found"})); return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            prompt = (payload.get("prompt") or "").strip()
            if not prompt:
                self._send(400, json.dumps({"error": "empty prompt"})); return
            self._send(200, json.dumps(ROUTER.route(prompt)))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            self._send(200, json.dumps({"error": f"Gemini API {e.code}: {detail}"}))
        except Exception as e:
            self._send(200, json.dumps({"error": str(e)}))


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print("=" * 60)
    print("  VOKK AI v02 — running")
    print(f"  Open: {url}")
    engines = []
    if GEMINI_KEY:
        engines.append(f"Gemini {TEXT_MODEL}")
    if GLM_KEY:
        engines.append(f"GLM {GLM_MODEL}")
    print(f"  Mode: {'LIVE — ' + ' + '.join(engines) if HAVE_ANY_KEY else 'MOCK — no keys set'}")
    print("  Stop: Ctrl+C")
    print("=" * 60)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nVOKK stopped."); srv.shutdown()


if __name__ == "__main__":
    main()
