"""Cached LangChain agents (small vs large) and a single invoke path for API + eval."""
from __future__ import annotations

import logging
import json
from typing import Literal
from langchain_core.messages import AIMessage, HumanMessage

from llm_factory import get_chat_llm
from prompting import (
    apply_self_reflection,
    build_chained_context,
    build_system_prompt,
    persona_instructions,
    strip_editor_meta_from_user_text,
)
from tools import fetch_user_profile, get_weather, record_visited_place, search_local_history, search_web

TOOLS = [search_local_history, fetch_user_profile, record_visited_place, search_web, get_weather]

PromptingMode = Literal["regular", "meta", "chaining", "self_reflection"]
_agents: dict[str, object] = {}
logger = logging.getLogger("walkietalkie.agent_runner")
MAX_HISTORY_MESSAGES = 14
MAX_CHARS_PER_MESSAGE = 4000
MAX_TOTAL_CHARS = 24000


def get_agent(tier: str, mode: PromptingMode):
    cache_key = f"{tier}:{mode}"
    if cache_key not in _agents:
        use_meta_prompt = mode != "regular"
        system_prompt = build_system_prompt() if use_meta_prompt else persona_instructions()
        logger.info("Initializing agent for tier=%s mode=%s", tier, mode)

        llm = get_chat_llm(tier)
        # Bind tools to LLM
        llm_with_tools = llm.bind_tools(TOOLS)
        _agents[cache_key] = llm_with_tools
    return _agents[cache_key]


def _transcript_for_reflection(messages: list) -> str:
    lines: list[str] = []
    for m in messages[-12:]:
        role = type(m).__name__
        content = getattr(m, "content", "")
        if isinstance(content, list):
            content = str(content)
        lines.append(f"{role}: {content[:1200]}")
    return "\n".join(lines)


def _trim_text(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    return content[:limit] + "\n...[truncated]..."


def _sanitize_messages(messages: list) -> list:
    """
    Keep only recent turns and hard-cap payload size to avoid provider context overflows.
    """
    recent = messages[-MAX_HISTORY_MESSAGES:]
    sanitized: list = []
    for m in recent:
        content = getattr(m, "content", "") or ""
        if isinstance(content, list):
            content = str(content)
        content = _trim_text(str(content), MAX_CHARS_PER_MESSAGE)
        if isinstance(m, HumanMessage):
            sanitized.append(HumanMessage(content=content))
        else:
            sanitized.append(AIMessage(content=content))

    total = sum(len(getattr(m, "content", "") or "") for m in sanitized)
    while total > MAX_TOTAL_CHARS and len(sanitized) > 1:
        dropped = sanitized.pop(0)
        total -= len(getattr(dropped, "content", "") or "")
    return sanitized


def run_chat_turn(
    formatted_messages: list,
    tier: str,
    user_id: str,
    city: str | None,
    latitude: float | None,
    longitude: float | None,
    prompting_mode: PromptingMode = "self_reflection",
) -> tuple[str, float]:
    """
    formatted_messages: LangChain HumanMessage/AIMessage list (user content already prepared).
    Returns (final_text, elapsed_seconds).
    """
    import time

    logger.info(
        "run_chat_turn start | tier=%s user_id=%s city=%s lat=%s lng=%s msg_count=%s",
        tier,
        user_id,
        city,
        latitude,
        longitude,
        len(formatted_messages or []),
    )
    mode: PromptingMode = prompting_mode if prompting_mode in ("regular", "meta", "chaining", "self_reflection") else "self_reflection"
    llm_with_tools = get_agent(tier, mode)
    formatted_messages = _sanitize_messages(formatted_messages or [])
    logger.info(
        "Sanitized context | messages=%s total_chars=%s",
        len(formatted_messages),
        sum(len(getattr(m, "content", "") or "") for m in formatted_messages),
    )
    if formatted_messages:
        last = formatted_messages[-1]
        if isinstance(last, HumanMessage):
            use_chain = mode in ("chaining", "self_reflection")
            chain = build_chained_context(user_id, city, latitude, longitude) if use_chain else ""
            if chain:
                last.content = chain + "\n" + last.content
                logger.debug("Applied chained context preview: %s", str(chain)[:600])

    t0 = time.time()

    # Simple tool calling loop
    messages = list(formatted_messages) if formatted_messages else []
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        # Check if model wants to call tools
        if hasattr(response, 'tool_calls') and response.tool_calls:
            # Execute tools
            for tool_call in response.tool_calls:
                tool_name = tool_call.get('name')
                tool_input = tool_call.get('args', {})
                logger.debug(f"Executing tool: {tool_name} with input: {tool_input}")

                # Find and execute the tool
                tool_result = None
                for tool in TOOLS:
                    if tool.name == tool_name:
                        try:
                            tool_result = tool.func(**tool_input)
                        except Exception as e:
                            tool_result = f"Error executing tool: {str(e)}"
                        break

                if tool_result is None:
                    tool_result = f"Tool {tool_name} not found"

                # Add tool result to messages
                messages.append(HumanMessage(content=str(tool_result)))
        else:
            # No more tool calls, exit loop
            break

    elapsed = time.time() - t0
    logger.info("Agent invoke complete | elapsed=%.3fs", elapsed)

    # Extract final response
    draft = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = getattr(msg, "content", "") or ""
            if isinstance(content, str):
                draft = content
                break

    if not draft and messages:
        draft = str(messages[-1])

    logger.debug("Model draft preview: %s", draft[:1200])

    # For reflection, build transcript from original messages
    transcript = _transcript_for_reflection(formatted_messages) if formatted_messages else ""

    use_reflection = mode == "self_reflection"
    polished = apply_self_reflection(tier, draft, transcript) if use_reflection else draft
    polished = strip_editor_meta_from_user_text(polished)
    logger.debug("Model polished preview: %s", (polished or "")[:1200])
    return polished, elapsed
