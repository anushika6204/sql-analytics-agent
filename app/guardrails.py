"""Input guard: NeMo Guardrails rail + built-in deterministic scanner.

Layering (both run for every request):
  1. NeMo Guardrails input rail (``guardrails_config/``) - if enabled and available.
  2. Built-in regex scanner - always on; also the logic behind the NeMo action.

If NeMo cannot start (not installed, bad config) the guard degrades to layer 2
and reports that in ``InputGuard.status`` rather than failing open.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from app.config import PROJECT_ROOT
from app.input_scanner import scan_input

log = logging.getLogger(__name__)

REFUSAL_PREFIX = "Security warning"
CONFIG_DIR = PROJECT_ROOT / "guardrails_config"


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""
    layer: str = ""  # which layer made the decision


class InputGuard:
    def __init__(self, use_nemo: bool = True):
        self._rails = None
        self.status = "built-in scanner only"
        if use_nemo:
            self._try_load_nemo()

    # -- NeMo ----------------------------------------------------------------
    def _try_load_nemo(self) -> None:
        try:
            from nemoguardrails import LLMRails, RailsConfig

            # NeMo instantiates the (unused) main LLM client at start-up, which
            # requires *a* key to be present. Input rails never call it.
            os.environ.setdefault("OPENAI_API_KEY", "not-used-by-input-rail")
            config = RailsConfig.from_path(str(CONFIG_DIR))
            self._rails = LLMRails(config)
            self.status = "NeMo Guardrails + built-in scanner"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, never fail open
            log.warning("NeMo Guardrails unavailable (%s); using built-in scanner only.", exc)
            self.status = f"built-in scanner only (NeMo unavailable: {type(exc).__name__})"
            self._rails = None

    def _nemo_check(self, text: str) -> GuardResult | None:
        """Run only the input rail. Returns a block result, or None if allowed."""
        from nemoguardrails.rails.llm.options import GenerationOptions, GenerationRailsOptions

        options = GenerationOptions(
            rails=GenerationRailsOptions(input=True, output=False, dialog=False, retrieval=False)
        )
        messages = [{"role": "user", "content": text}]

        async def _run():
            return await self._rails.generate_async(messages=messages, options=options)

        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False
        if in_loop:  # e.g. called from an async context: run in a helper thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(asyncio.run, _run()).result()
        else:
            response = asyncio.run(_run())

        content = ""
        resp = getattr(response, "response", response)
        if isinstance(resp, list) and resp:
            content = (resp[0] or {}).get("content", "") or ""
        elif isinstance(resp, dict):
            content = resp.get("content", "") or ""
        elif isinstance(resp, str):
            content = resp
        if content.startswith(REFUSAL_PREFIX):
            return GuardResult(False, content, "nemo-guardrails")
        return None

    # -- public --------------------------------------------------------------
    def check(self, text: str) -> GuardResult:
        if self._rails is not None:
            try:
                blocked = self._nemo_check(text)
                if blocked:
                    detail = scan_input(text).reason  # specific rule name, if known
                    return GuardResult(False, detail or blocked.reason, blocked.layer)
            except Exception as exc:  # noqa: BLE001
                log.warning("NeMo check failed (%s); relying on built-in scanner.", exc)
        scan = scan_input(text)
        if not scan.allowed:
            return GuardResult(False, scan.reason, "built-in-scanner")
        return GuardResult(True, "", "passed")
