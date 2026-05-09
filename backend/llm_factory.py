"""OpenRouter-backed chat/vision + OpenRouter/Ollama embeddings."""
from __future__ import annotations

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings

import config

_embeddings: OpenAIEmbeddings | OllamaEmbeddings | None = None


def _openrouter_base_url() -> str:
    config.assert_api_config()
    return config.openrouter_base_url()


def _openrouter_headers() -> dict[str, str]:
    headers: dict[str, str] = {"X-Title": config.openrouter_title()}
    referer = config.openrouter_referer()
    if referer:
        headers["HTTP-Referer"] = referer
    return headers


def _ollama_chat(model: str, temperature: float = 0.7) -> ChatOllama:
    return ChatOllama(model=model, temperature=temperature, base_url=config.ollama_base_url())


def _openrouter_chat(model: str, temperature: float = 0.7) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=config.openrouter_api_key(),
        base_url=_openrouter_base_url(),
        default_headers=_openrouter_headers(),
    )


def get_chat_llm(tier: str):
    """Return a model chain with automatic fallbacks.

    small : nvidia/nemotron-nano-9b-v2:free  → Ollama small
    large : nvidia/nemotron-3-nano-30b-a3b:free
              → google/gemma-4-31b-it:free
              → Ollama large
    """
    if config.force_ollama_fallback():
        ollama_model = config.OLLAMA_LARGE_LLM_MODEL if tier == "large" else config.OLLAMA_SMALL_LLM_MODEL
        return _ollama_chat(ollama_model)

    if tier == "large":
        primary = _openrouter_chat(config.LARGE_LLM_MODEL)
        ollama_fallback = _ollama_chat(config.OLLAMA_LARGE_LLM_MODEL)
        return primary.with_fallbacks([ollama_fallback])

    primary_small = _openrouter_chat(config.SMALL_LLM_MODEL)
    ollama_small_fallback = _ollama_chat(config.OLLAMA_SMALL_LLM_MODEL)
    return primary_small.with_fallbacks([ollama_small_fallback])


def get_embedding_model() -> OpenAIEmbeddings | OllamaEmbeddings:
    global _embeddings
    if _embeddings is None:
        if config.OPENROUTER_EMBEDDING_MODEL:
            _embeddings = OpenAIEmbeddings(
                model=config.OPENROUTER_EMBEDDING_MODEL,
                api_key=config.openrouter_api_key(),
                base_url=_openrouter_base_url(),
                default_headers=_openrouter_headers(),
            )
        elif config.force_ollama_fallback():
            _embeddings = OllamaEmbeddings(
                model=config.EMBEDDING_MODEL,
                base_url=config.ollama_base_url(),
            )
        else:
            raise RuntimeError(
                "Set OPENROUTER_EMBEDDING_MODEL in backend/.env for OpenRouter-only mode."
            )
    return _embeddings
