"""Custom NeMo Guardrails action used by the input rail."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from nemoguardrails.actions import action

# Make the project root importable when NeMo loads this file from the config dir.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.input_scanner import scan_input  # noqa: E402


@action(name="check_input_safety")
async def check_input_safety(context: Optional[dict] = None) -> bool:
    """Return True when the user's message is safe to forward to the LLM."""
    message = (context or {}).get("user_message", "")
    return scan_input(message).allowed
