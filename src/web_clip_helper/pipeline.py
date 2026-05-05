"""Compatibility shim — module moved to web_clip_helper.services.clip."""
from web_clip_helper.services.clip import *  # noqa: F401,F403
from web_clip_helper.services.clip import _replace_image_urls, _store_and_index, _enrich_with_llm  # noqa: F401
