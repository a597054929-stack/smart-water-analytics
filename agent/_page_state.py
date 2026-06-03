"""Process-wide page context state.

Lives in its own module so that LangGraph's tool runtime, which may copy
or rebind tool functions into its own execution namespace, still sees
the same global dict. Previously the state was a module-level variable
in agent_tools.py, and the @tool-wrapped accessor implicitly resolved
_PAGE_CONTEXT via the tool function's globals — which broke in some
runtime configurations.
"""

# Single source of truth. Mutated by set_page_context(), read by
# get_page_context(). A dict (not a dataclass) so callers can store
# arbitrary keys without changing the type.
PAGE_STATE: dict = {}


def set_page_context(ctx) -> None:
    """Store the latest page state. Pass None to clear."""
    global PAGE_STATE
    PAGE_STATE = ctx or {}


def get_page_context() -> dict:
    """Return a snapshot of the latest page state."""
    return dict(PAGE_STATE)
