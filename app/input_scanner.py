"""Deterministic scan of raw user text for malicious patterns.

Used by (a) the NeMo Guardrails custom action and (b) as the built-in fallback
layer, so the same rules apply whether or not NeMo is available.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (rule name, compiled pattern)
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("script tag", re.compile(r"<\s*/?\s*script\b|javascript\s*:|on(error|load)\s*=", re.I)),
    ("tautology", re.compile(
        r"\b(or|and)\s+(['\"]?)(\w+)\2\s*=\s*(['\"]?)\3\4(?!\w)"   # OR 1=1, OR 'a'='a'
        r"|\b(or|and)\s+(true|1)\b(?!\s*[<>])", re.I)),
    ("SQL comment sequence", re.compile(r"--|/\*|\*/|(?<!\w)#\s*$")),
    ("stacked statement", re.compile(
        r";\s*(drop|delete|insert|update|alter|truncate|create|grant|revoke|exec|attach|pragma)\b", re.I)),
    ("destructive SQL", re.compile(
        r"\b(drop|truncate)\s+(table|database|schema|view|index)\b"
        r"|\bdelete\s+from\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b"
        r"|\balter\s+table\b|\bcreate\s+(table|user|database)\b|\bgrant\s+\w+\s+on\b", re.I)),
    ("union injection", re.compile(r"\bunion\s+(all\s+)?select\b", re.I)),
    ("dangerous function", re.compile(
        r"\b(xp_cmdshell|load_extension|pg_sleep|sleep\s*\(|benchmark\s*\(|pg_read_file|lo_import|into\s+outfile)\b", re.I)),
    ("prompt injection", re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions|disregard\s+(the\s+)?system\s+prompt", re.I)),
]

MAX_INPUT_CHARS = 1000


@dataclass(frozen=True)
class ScanResult:
    allowed: bool
    reason: str = ""


def scan_input(text: str) -> ScanResult:
    """Return whether ``text`` looks safe to forward to the LLM."""
    if text is None or not text.strip():
        return ScanResult(False, "Empty question.")
    if len(text) > MAX_INPUT_CHARS:
        return ScanResult(False, f"Input too long (>{MAX_INPUT_CHARS} characters).")
    for name, pattern in _RULES:
        if pattern.search(text):
            return ScanResult(False, f"Blocked by input rule: {name}.")
    return ScanResult(True)
