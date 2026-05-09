"""Environment-driven settings for OpenRouter (chat/vision) + optional embeddings."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Always load backend/.env, regardless of process working directory.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

        
def openrouter_api_key() -> str:
    return (os.getenv("OPENROUTER_API_KEY") or "").strip()


def openrouter_base_url() -> str:
    return (os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").strip()


def openrouter_referer() -> str:
    return (os.getenv("OPENROUTER_HTTP_REFERER") or "").strip()


def openrouter_title() -> str:
    return (os.getenv("OPENROUTER_X_TITLE") or "WalkieTalkie-VA").strip()


def ollama_base_url() -> str:
    """Optional fallback for embeddings when OPENROUTER_EMBEDDING_MODEL is unset."""
    return (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip()

def force_ollama_fallback() -> bool:
    return (os.getenv("FORCE_OLLAMA_FALLBACK") or "false").lower() in ("1", "true", "yes")

def openweathermap_api_key() -> str:
    """OpenWeatherMap API key for the get_weather tool."""
    return (os.getenv("OPENWEATHERMAP_API_KEY") or "").strip()


def serpapi_api_key() -> str:
    """SerpAPI key for Google Lens image recognition and search."""
    return (os.getenv("SERPAPI_API_KEY") or "").strip()


def itinerary_timeout_seconds() -> float:
    """Max seconds to wait for one itinerary model call before fallback."""
    try:
        return float(os.getenv("ITINERARY_TIMEOUT_SECONDS") or "20")
    except Exception:
        return 20.0


# OpenRouter chat/vision model IDs.
SMALL_LLM_MODEL: str = os.getenv("SMALL_LLM_MODEL", "nvidia/nemotron-nano-9b-v2:free")
LARGE_LLM_MODEL: str = os.getenv("LARGE_LLM_MODEL", "nvidia/nemotron-3-nano-30b-a3b:free")
VISION_LLM_MODEL: str = os.getenv("VISION_LLM_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")

# Optional OpenRouter embedding model (if empty, Ollama embeddings are used).
OPENROUTER_EMBEDDING_MODEL: str = os.getenv("OPENROUTER_EMBEDDING_MODEL", "").strip()
# Ollama fallback embedding model when OPENROUTER_EMBEDDING_MODEL is unset.
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest")
OLLAMA_SMALL_LLM_MODEL: str = os.getenv("OLLAMA_SMALL_LLM_MODEL", "llama3.2:latest")
OLLAMA_LARGE_LLM_MODEL: str = os.getenv("OLLAMA_LARGE_LLM_MODEL", "qwen2.5-coder:14b")
OLLAMA_VISION_LLM_MODEL: str = os.getenv("OLLAMA_VISION_LLM_MODEL", "llama3.2-vision:latest")

REFLECTION_ENABLED: bool = os.getenv("REFLECTION_ENABLED", "true").lower() in ("1", "true", "yes")
HERO_CHAIN_PREFETCH: bool = os.getenv("HERO_CHAIN_PREFETCH", "true").lower() in ("1", "true", "yes")

# Supported trip cities (must match walkie-talkie-app `CITIES`).
HERO_CITIES: tuple[str, ...] = (
    "Boston",
    "Chicago",
    "Kolkata",
    "Los Angeles",
    "Miami",
    "New York",
    "Philadelphia",
    "San Francisco",
    "Seattle",
    "Washington DC",
)


def assert_api_config() -> None:
    if force_ollama_fallback():
        return
    if not openrouter_api_key():
        raise RuntimeError("Set OPENROUTER_API_KEY in backend/.env")
