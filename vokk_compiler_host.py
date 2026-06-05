#!/usr/bin/env python3
"""
vokk_compiler_host.py — early compiler-host layer for VOKK-native sources.

This does not replace the Python server yet. It is the bridge that lets the
runtime treat `.vokk` sources as first-class inputs instead of only loose text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from vokk_lang import parse_cortex, run_vokk
from vokk_runtime_lang import compile_runtime_source
from vokk_surface import run_surface


class VokkCompilerHost:
    def __init__(self, root: Path | None = None):
        self.root = (root or Path(__file__).parent).resolve()

    def load_cortex(self, rel: str = "cortex.vokk") -> Dict[str, Any]:
        path = self.root / rel
        src = path.read_text(errors="ignore")
        return {"path": str(path), "source": src, "parsed": parse_cortex(src)}

    def compile_surface_source(self, source: str) -> List[Dict[str, Any]]:
        return run_surface(source)

    def compile_vokk_source(self, source: str) -> List[Dict[str, Any]]:
        return run_vokk(source)

    def compile_runtime_source(self, source: str) -> Dict[str, Any]:
        return compile_runtime_source(source)

    def compile_file(self, rel: str) -> Dict[str, Any]:
        path = self.root / rel
        src = path.read_text(errors="ignore")
        if "interface " in src or "world3d " in src:
            return {"kind": "surface", "path": str(path), "artifacts": self.compile_surface_source(src)}
        if any(token in src for token in ("app ", "route ", "store ", "session ", "action ", "component ")):
            return {"kind": "runtime", "path": str(path), "artifacts": [self.compile_runtime_source(src)]}
        return {"kind": "vokkscript", "path": str(path), "artifacts": self.compile_vokk_source(src)}
