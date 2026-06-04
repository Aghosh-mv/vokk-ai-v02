#!/usr/bin/env python3
"""
vokk_cognitive.py — small cognitive workflow helpers for planning, comparing
evidence, and building tighter retrieval focus terms.

This is not a magic AGI layer. It is a real workflow module VOKK can call to:
- frame the task
- derive focus terms
- compare local and web evidence
- summarize coverage gaps
"""

from __future__ import annotations

import re
from typing import Dict, List


class CognitiveWorkflow:
    STOP = {
        "the", "this", "that", "with", "from", "into", "about", "have", "will",
        "your", "their", "there", "which", "what", "when", "where", "while",
        "please", "make", "build", "using", "need", "want", "full", "real",
        "then", "after", "also", "only",
    }

    def focus_terms(self, prompt: str, limit: int = 10) -> List[str]:
        words = re.findall(r"[a-z0-9_]{3,}", (prompt or "").lower())
        out: List[str] = []
        for word in words:
            if word in self.STOP or word in out:
                continue
            out.append(word)
            if len(out) >= limit:
                break
        return out

    def plan(self, prompt: str) -> Dict[str, object]:
        terms = self.focus_terms(prompt, 12)
        stages = ["frame", "retrieve_local", "retrieve_web", "compare", "answer"]
        if re.search(r"\b(code|runtime|compiler|host|renderer|api|server)\b", prompt.lower()):
            stages.insert(3, "inspect_implementation")
        return {
            "goal": (prompt or "").strip()[:220],
            "focus_terms": terms,
            "focus_query": " ".join(terms[:6]),
            "stages": stages,
        }

    def compare_sources(self, local_titles: List[str], web_titles: List[str]) -> Dict[str, List[str]]:
        local_words = {w for title in local_titles for w in re.findall(r"[a-z0-9_]{3,}", title.lower())}
        web_words = {w for title in web_titles for w in re.findall(r"[a-z0-9_]{3,}", title.lower())}
        overlap = sorted(local_words & web_words)[:12]
        only_local = sorted(local_words - web_words)[:12]
        only_web = sorted(web_words - local_words)[:12]
        return {
            "overlap": overlap,
            "only_local": only_local,
            "only_web": only_web,
        }
