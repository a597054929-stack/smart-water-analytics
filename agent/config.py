"""
LLM configuration for the Agent.

Supports multiple providers via environment variables:
  - LLM_PROVIDER: "deepseek", "openai", "anthropic", "mimo" (default: "openai")
  - LLM_API_KEY: API key for the selected provider
  - LLM_BASE_URL: (optional) custom base URL
  - LLM_MODEL: (optional) model name override

Falls back to ~/.openclaw/openclaw.json if env vars not set.
"""
import json, os


def _load_openclaw_config():
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f).get("models", {}).get("providers", {})
    return {}


def get_llm_config():
    provider = os.environ.get("LLM_PROVIDER", "openai")

    # 1. Try environment variables first
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")

    if api_key:
        return {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url or _default_base_url(provider),
            "model": model or _default_model(provider),
        }

    # 2. Fall back to openclaw.json
    providers = _load_openclaw_config()

    if provider == "deepseek" and "deepseek" in providers:
        ds = providers["deepseek"]
        return {
            "provider": "deepseek",
            "api_key": ds["apiKey"],
            "base_url": ds.get("baseUrl", "https://api.deepseek.com"),
            "model": model or "deepseek-chat",
        }

    if provider == "mimo" and "xiaomi-coding" in providers:
        m = providers["xiaomi-coding"]
        # Get model name from config or use default
        models_list = m.get("models", [])
        default_model = models_list[0]["id"] if models_list else "mimo-v2.5-pro"
        return {
            "provider": "mimo",
            "api_key": m["apiKey"],
            "base_url": m["baseUrl"],
            "model": model or default_model,
        }

    if provider == "nvidia" and "nvidia" in providers:
        n = providers["nvidia"]
        models_list = n.get("models", [])
        default_model = models_list[0]["id"] if models_list else "z-ai/glm5"
        return {
            "provider": "nvidia",
            "api_key": n["apiKey"],
            "base_url": n["baseUrl"],
            "model": model or default_model,
        }

    if provider == "anthropic":
        return {
            "provider": "anthropic",
            "api_key": api_key or "",
            "base_url": base_url or "",
            "model": model or "claude-sonnet-4-6",
        }

    raise ValueError(
        f"No API key found for provider '{provider}'. "
        f"Set LLM_API_KEY env var or configure ~/.openclaw/openclaw.json"
    )


def _default_base_url(provider):
    urls = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "anthropic": "https://api.anthropic.com",
    }
    return urls.get(provider, "")


def _default_model(provider):
    models = {
        "openai": "gpt-4o-mini",
        "deepseek": "deepseek-chat",
        "mimo": "mimo-v2.5",
    }
    return models.get(provider, "gpt-4o-mini")
