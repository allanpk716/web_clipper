"""Adapter registry — imports and registers all built-in adapters.

Import this module at app startup to populate ``adapter_router`` with
the GitHub adapter and set the generic web adapter as the default
fallback.

Usage::

    import web_clip_helper.adapters._registry  # noqa: F401
"""

from __future__ import annotations

from ..adapter import adapter_router
from .github import GitHubAdapter
from .generic import GenericWebAdapter
from .weibo import WeiboAdapter
from .wechat import WeChatAdapter

__all__ = ["GitHubAdapter", "GenericWebAdapter", "WeiboAdapter", "WeChatAdapter"]

# Re-export for convenience
__all__: list[str]  # type: ignore[no-redef]

# Note: GitHubAdapter is already registered via @register_adapter decorator
# on import. We just need to ensure the import happens.

# Store a reference to the fallback adapter class so adapter.py can use it.
_FALLBACK_ADAPTER = GenericWebAdapter
