"""Compatibility shim — module moved to web_clip_helper.services.llm."""
from web_clip_helper.services.llm import *  # noqa: F401,F403
from web_clip_helper.services.llm import MAX_CONTENT_CHARS, _SafeDict  # noqa: F401
from openai import OpenAI  # noqa: F401 — re-exported for mock patching compatibility
