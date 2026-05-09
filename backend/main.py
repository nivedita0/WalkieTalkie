import json
import asyncio
import re
import base64
import binascii
import logging
import os
import threading
import time
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

import config
from agent_runner import run_chat_turn
from database import (
    canonicalize_user_id,
    create_session,
    ensure_user,
    get_chat_history,
    get_city_index_status,
    get_user_by_session,
    get_user_preferences,
    purge_expired_sessions,
    revoke_session,
    save_chat_message,
    save_visited_place,
    update_user_preferences,
)
from ingest_data import ingest_city
from llm_factory import get_chat_llm
from prompting import build_system_prompt, strip_editor_meta_from_user_text
from tools import (
    scrape_live_context,
    scrape_static_history,
    search_local_history,
    search_web,
    get_weather,
    serpapi_google_lens_lookup,
)

_LOG_LEVEL = (os.getenv("APP_LOG_LEVEL") or "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("walkietalkie.main")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str
    content: str
    images: Optional[List[str]] = None


class ChatRequest(BaseModel):
    """llm_tier: 'small' | 'large' for dual-model experiments. Legacy `model` is still accepted."""

    model: Optional[str] = None
    llm_tier: Optional[str] = "large"
    messages: List[Message]
    stream: Optional[bool] = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = "San Francisco"
    session_token: Optional[str] = None
    prompting_mode: Optional[str] = "self_reflection"


class ItineraryRequest(BaseModel):
    city: str
    dates: Optional[str] = None
    days: Optional[int] = 1
    budget: Optional[str] = "Moderate"
    llm_tier: Optional[str] = "large"


class HolidayBriefingRequest(BaseModel):
    city: str
    start_date: Optional[str] = None  # YYYY-MM-DD
    days: int = 1


class WalkStoryRequest(BaseModel):
    city: str
    place_title: str
    anecdote: str
    llm_tier: Optional[str] = "small"


class SignInRequest(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    budget: Optional[int] = None
    dietary: Optional[str] = None
    country: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    session_token: str
    budget: Optional[int] = None
    dietary: Optional[str] = None
    country: Optional[str] = None


class VisitedPlaceRequest(BaseModel):
    session_token: str
    city: str
    place_name: str


class LogoutRequest(BaseModel):
    session_token: str


class CityWarmupRequest(BaseModel):
    city: str


_PLACEHOLDER_TITLE_RE = re.compile(
    r"\b(restaurant|place|spot|museum|attraction|landmark)\s*\d+\b|\b(tbd|to be decided|unknown)\b",
    re.IGNORECASE,
)


def _is_placeholder_title(title: str) -> bool:
    if not title:
        return True
    return bool(_PLACEHOLDER_TITLE_RE.search(title.strip()))


def _itinerary_has_placeholder_names(nodes: dict) -> bool:
    for item in (nodes.get("places") or []) + (nodes.get("eats") or []):
        if _is_placeholder_title(str(item.get("title", ""))):
            return True
    return False


def _normalize_eats_quota(nodes: dict, max_ratio: float = 0.25) -> None:
    """
    Keep food suggestions as a small part of the route by default.
    """
    place_count = len(nodes.get("places") or [])
    eats = nodes.get("eats") or []
    if not eats:
        return
    max_eats = max(1, int(place_count * max_ratio)) if place_count else 1
    kept_eats = eats[:max_eats]
    removed_ids = {e.get("id") for e in eats[max_eats:] if e.get("id")}
    nodes["eats"] = kept_eats
    if not removed_ids:
        return
    for day in nodes.get("itinerary", []):
        day["plan"] = [pid for pid in day.get("plan", []) if pid not in removed_ids]


def _extract_json_object(raw: str) -> dict:
    content = (raw or "").strip()
    if "<final_answer>" in content and "</final_answer>" in content:
        content = content.split("<final_answer>")[-1].split("</final_answer>")[0].strip()
    elif "</planning>" in content:
        content = content.split("</planning>")[-1].strip()
    if content.startswith("```json"):
        content = content[7:-3]
    if content.startswith("```"):
        content = content[3:-3]
    start_idx = content.find("{")
    end_idx = content.rfind("}")
    if start_idx != -1 and end_idx != -1:
        content = content[start_idx : end_idx + 1]
    return json.loads(content)


def _normalize_tier_value(raw_tier: str | None) -> str:
    t = (raw_tier or "large").lower()
    if t in ("small", "s"):
        return "small"
    return "large"


def _tier_model_candidates(tier: str) -> list[str]:
    if config.force_ollama_fallback():
        return [config.OLLAMA_LARGE_LLM_MODEL if tier == "large" else config.OLLAMA_SMALL_LLM_MODEL]
    if tier == "large":
        return [
            config.LARGE_LLM_MODEL,
            config.OLLAMA_LARGE_LLM_MODEL,
        ]
    return [config.SMALL_LLM_MODEL, config.OLLAMA_SMALL_LLM_MODEL]


async def _invoke_itinerary_model(prompt: str, tier: str) -> str:
    """
    Invoke itinerary model and wait for provider response.
    """
    model_tiers = [tier, tier]
    model_candidates = _tier_model_candidates(tier)
    provider_mode = "ollama_only" if config.force_ollama_fallback() else "openrouter_with_fallbacks"
    print(
        f">>> [ITINERARY GENERATION] model route | tier={tier} | mode={provider_mode} | "
        f"candidates={model_candidates}"
    )
    last_err = None
    for attempt_idx, model_tier in enumerate(model_tiers, start=1):
        try:
            print(
                f">>> [ITINERARY GENERATION] attempt={attempt_idx} invoking tier={model_tier} "
                f"(fallback chain may apply inside LLM client)"
            )
            llm = get_chat_llm(model_tier)
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            return (resp.content or "").strip()
        except Exception as e:
            last_err = e
            print(
                f">>> [ITINERARY GENERATION] tier={model_tier} failed "
                f"(attempt {attempt_idx}): {repr(e)}"
            )
            continue
    raise RuntimeError(f"all itinerary model attempts failed: {last_err}")


def _resolve_tier(request: ChatRequest) -> str:
    t = (request.llm_tier or "large").lower()
    if t in ("small", "s"):
        return "small"
    if t in ("large", "l"):
        return "large"
    m = (request.model or "").lower()
    if m in ("phi4", "small", "vision", "gemini-flash-lite"):
        return "small"
    return "large"


def _resolve_prompting_mode(raw_mode: str | None) -> str:
    mode = (raw_mode or "self_reflection").strip().lower()
    if mode in ("regular", "meta", "chaining", "self_reflection"):
        return mode
    return "self_reflection"


def _format_lens_matches(lens: dict, max_results: int = 5) -> str:
    matches = lens.get("matches") or []
    if not matches:
        return "No image matches found."
    lines = []
    for i, m in enumerate(matches[:max_results], start=1):
        lines.append(
            f"{i}. title={m.get('title','')} | snippet={m.get('snippet','')} | link={m.get('link','')}"
        )
    return "\n".join(lines)


def _preview(text: str, limit: int = 800) -> str:
    return (text or "")[:limit]


def _friendly_error_message(err: Exception, context: str = "chat") -> str:
    """
    Convert provider/internal exceptions into safe user-facing text.
    """
    msg = str(err or "")
    low = msg.lower()
    if "ratelimit" in low or "rate limit" in low or "429" in low:
        return (
            "I'm getting rate-limited right now. Please try again in a bit, "
            "or switch model tier if available."
        )
    if context == "image":
        return "I couldn't process that image right now. Please try another image or try again shortly."
    return "I couldn't complete that request right now. Please try again in a moment."


_CITY_INDEX_TTL_SEC = 14 * 24 * 3600
_city_warmup_locks: dict[str, threading.Lock] = {}


def _city_is_ready_fresh(city: str) -> bool:
    st = get_city_index_status(city)
    if not st or st.get("status") != "ready":
        return False
    return int(time.time()) - int(st.get("updated_at") or 0) < _CITY_INDEX_TTL_SEC


def _ensure_city_warmup_async(city: str) -> None:
    city = (city or "").strip()
    if not city:
        return
    if _city_is_ready_fresh(city):
        return

    lock = _city_warmup_locks.setdefault(city, threading.Lock())
    if lock.locked():
        return

    def _job():
        if not lock.acquire(blocking=False):
            return
        try:
            logger.info("City warmup start | city=%s", city)
            result = ingest_city(city, max_sources=8)
            logger.info("City warmup complete | city=%s result=%s", city, result)
        except Exception as e:
            logger.exception("City warmup failed | city=%s err=%s", city, e)
        finally:
            lock.release()

    threading.Thread(target=_job, daemon=True).start()


async def stream_response(text: str):
    words = text.split(" ")
    for word in words:
        chunk = json.dumps({"message": {"content": word + " "}})
        yield chunk + "\n"
        await asyncio.sleep(0.02)


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info("--- NEW REQUEST ---")
    tier = _resolve_tier(request)
    prompting_mode = _resolve_prompting_mode(request.prompting_mode)
    logger.info(
        "chat request meta | tier=%s prompting_mode=%s city=%s stream=%s messages=%s",
        tier,
        prompting_mode,
        request.city,
        request.stream,
        len(request.messages or []),
    )

    session = get_user_by_session((request.session_token or "").strip())
    user_id = session["user_id"] if session else "guest_local"
    formatted_messages = []
    last_user_msg_idx: int | None = None

    last_raw_user_message = ""
    if not request.messages:
        error_msg = "Please send at least one message so I can help."
        return StreamingResponse(stream_response(error_msg), media_type="application/x-ndjson")

    for m in request.messages:
        if m.role == "system":
            # Preserve frontend/system constraints so prompt strategy stays aligned.
            formatted_messages.append(SystemMessage(content=m.content))
        elif m.role == "user":
            last_raw_user_message = m.content or ""
            content_str = m.content
            logger.debug("user message preview: %s", _preview(m.content))
            if m.images and len(m.images) > 0:
                logger.info(
                    "Image upload detected | image_count=%s | first_image_chars=%s",
                    len(m.images),
                    len(m.images[0] or ""),
                )
                try:
                    city = request.city or "San Francisco"
                    raw_img = m.images[0] or ""
                    if "," in raw_img:
                        raw_img = raw_img.split(",", 1)[1]
                    try:
                        image_bytes = base64.b64decode(raw_img, validate=False)
                    except (binascii.Error, ValueError):
                        image_bytes = b""

                    lens = serpapi_google_lens_lookup(image_bytes=image_bytes, city=city, max_results=5) if image_bytes else {
                        "ok": False,
                        "error": "Invalid image payload",
                        "matches": [],
                    }
                    lens_block = _format_lens_matches(lens, max_results=5)
                    logger.info(
                        "Image lookup result | ok=%s matches=%s error=%s",
                        lens.get("ok"),
                        len(lens.get("matches") or []),
                        lens.get("error", ""),
                    )
                    logger.debug("Lens match block preview: %s", _preview(lens_block, 1200))

                    # Targeted web context synthesis from image matches and user intent.
                    if lens.get("ok") and (lens.get("matches") or []):
                        top_title = str((lens.get("matches") or [{}])[0].get("title", "")).strip()
                        web_query = f"{city} {top_title} {m.content}".strip()
                    elif lens.get("ok"):
                        web_query = f"{city} {m.content}".strip()
                    else:
                        # Avoid propagating failure/error strings as web search query content.
                        web_query = f"{city} image identification from user upload".strip()
                    logger.info("Image web query: %s", _preview(web_query, 500))
                    web_context = search_web.invoke(web_query)
                    logger.debug("Image web context preview: %s", _preview(str(web_context), 1500))

                    is_menu_query = any(k in (m.content or "").lower() for k in ["menu", "dish", "eat", "food"])
                    if is_menu_query:
                        instruction = (
                            "Instruction: Use image recognition matches + web context to identify likely restaurant/menu, "
                            "then recommend the most authentic or popular local dish with a short why."
                        )
                    else:
                        instruction = (
                            "Instruction: Use image recognition matches + web context to identify the place/mural, "
                            "then explain its story (what it is, why it matters)."
                        )

                    if not lens.get("ok"):
                        content_str = (
                            f"[SERPAPI GOOGLE LENS STATUS]\nfailed={lens.get('error','unknown')}\n\n"
                            f"[WEB SEARCH CONTEXT]\n{str(web_context)[:2200]}\n\n"
                            "Instruction: Be transparent that image recognition lookup failed. "
                            "Answer from available context; if uncertain, clearly say so."
                        )
                    elif lens.get("matches"):
                        content_str = (
                            f"[SERPAPI GOOGLE LENS TOP 5 MATCHES]\n{lens_block}\n\n"
                            f"[WEB SEARCH CONTEXT]\n{str(web_context)[:2200]}\n\n"
                            f"{instruction}"
                        )
                    else:
                        content_str = (
                            "[SERPAPI GOOGLE LENS TOP 5 MATCHES]\nNo confident matches returned.\n\n"
                            f"[WEB SEARCH CONTEXT]\n{str(web_context)[:2200]}\n\n"
                            "Instruction: Tell the user no confident image match was found. "
                            "Then provide a cautious answer from web context."
                        )
                except Exception as e:
                    logger.exception("Image research processing failed: %s", e)

            formatted_messages.append(HumanMessage(content=content_str))
            last_user_msg_idx = len(formatted_messages) - 1
        else:
            formatted_messages.append(AIMessage(content=m.content))

    has_device_gps = request.latitude is not None and request.longitude is not None
    if has_device_gps:
        gps_line = (
            f"DEVICE_GPS_AVAILABLE=true; Lat={request.latitude}; Long={request.longitude}. "
            "You may tie the reply to this approximate area when it helps."
        )
    else:
        gps_line = (
            "DEVICE_GPS_AVAILABLE=false. "
            "Do NOT tell the user their GPS, location pin, or device places them in a neighborhood "
            "unless they stated their whereabouts in their own words. "
            "Use focus_city for general guidance only."
        )
    city = request.city or "San Francisco"
    _ensure_city_warmup_async(city)
    if last_user_msg_idx is None:
        error_msg = "Please include a user message in the chat payload."
        return StreamingResponse(stream_response(error_msg), media_type="application/x-ndjson")
    formatted_messages[last_user_msg_idx].content = (
        f"Backend context: user_id={user_id}; {gps_line} focus_city={city}.\n\n"
        + formatted_messages[last_user_msg_idx].content
    )

    try:
        final_answer, generation_time = run_chat_turn(
            formatted_messages,
            tier=tier,
            user_id=user_id,
            city=city,
            latitude=request.latitude if has_device_gps else None,
            longitude=request.longitude if has_device_gps else None,
            prompting_mode=prompting_mode,
        )
        # Save only the last user turn + final assistant response for history view.
        user_turn_text = (last_raw_user_message or "").strip()
        if request.messages and request.messages[-1].images:
            user_turn_text = f"{user_turn_text}\n[image_uploaded=true]"
        # Persist history only for authenticated sessions.
        if session:
            save_chat_message(user_id=user_id, city=city, role="user", content=user_turn_text)
            save_chat_message(user_id=user_id, city=city, role="assistant", content=final_answer)
        logger.info("generation complete | tier=%s elapsed=%.3fs", tier, generation_time)
        logger.debug("final answer preview: %s", _preview(final_answer, 2000))
        return StreamingResponse(stream_response(final_answer), media_type="application/x-ndjson")
    except Exception as e:
        import traceback

        logger.error("INTERNAL ERROR TRACEBACK:\n%s", traceback.format_exc())
        error_msg = _friendly_error_message(e, context="chat")
        return StreamingResponse(stream_response(error_msg), media_type="application/x-ndjson")


@app.post("/api/synthesize-itinerary")
async def synthesize_itinerary(req: ItineraryRequest):
    if req.city not in config.HERO_CITIES:
        return {
            "error": f"Itinerary synthesis is scoped to hero cities: {', '.join(config.HERO_CITIES)}",
            "places": [],
            "eats": [],
            "itinerary": [],
        }

    itinerary_tier = _normalize_tier_value(req.llm_tier)
    itinerary_candidates = _tier_model_candidates(itinerary_tier)
    provider_mode = "ollama_only" if config.force_ollama_fallback() else "openrouter_with_fallbacks"
    print(f"\n--- ITINERARY {req.days} days | {req.city} | {req.dates} | tier={itinerary_tier} ---")

    static_history = scrape_static_history.invoke(req.city)
    live_context = ""
    if req.dates and req.dates.strip():
        live_context = scrape_live_context.invoke({"city": req.city, "date_range": req.dates})

    combined_context = (
        f"--- STATIC HISTORY ---\n{str(static_history)[:2500]}\n\n"
        f"--- LIVE EVENTS & WEATHER ---\n{str(live_context)[:1000]}"
    )

    prompt = f"""You are a travel agent creating a WALKABLE, LOCALITY-FIRST itinerary for {req.city} only.
Duration: {req.days} days. Budget: {req.budget}.

GEOGRAPHY RULES (critical):
- Each day must focus on ONE primary neighborhood / district (or two ADJACENT areas only). Name it in "locality".
- For each day, EVERY stop in "plan" must be places you could reasonably walk between the same day (roughly within ~2 km total spread, same side of town). Do NOT jump from e.g. Fisherman's Wharf to Outer Sunset on the same day.
- Order stops in "plan" as a sensible walking loop or north-to-south stroll through that area — not random city-wide hops.
- Prefer famous sights that sit near each other in real geography; use accurate lat/lng for {req.city}.
- Validate the days it is open based on the travel dates, explicitly checking for 'free museum days' or mapping out the cheapest admission options.
- If the budget is low, bias eats toward that neighborhood too.

CONTENT PRIORITY RULES (critical):
- Prioritize history, architecture, museums, artisan districts, and local culture.
- Food must be a SMALL part of the trip unless the user explicitly asks for a food-focused itinerary.
- Target mix: ~75-90% history/art/culture stops and <=25% food stops.
- Use REAL place names only (proper nouns). NEVER output placeholders like "Kolkata Restaurant 1", "Place 2", "TBD", or generic numbered names.
- If uncertain about a venue name, omit it rather than inventing one.

First, write a <planning> block where you outline your logic step-by-step:
Step 1: Calculate the distance between the requested locations. Are they actually near each other?
Step 2: Verify that all locations are currently open on the requested dates.
Step 3: Double-check that your plan does not involve jumping across town.

Once you have verified the plan in the <planning> block, output your final answer inside a <final_answer> block. 
Inside the <final_answer> block, output EXACTLY a JSON object with keys: "places", "eats", "itinerary".

- "places": array of {{ "id", "title", "lat", "lng", "anecdote", "visited": false }}. Each anecdote should mention the neighborhood or street context (locality), not generic directions.
- "eats": same shape; prefer eateries in or next to the day's area, but keep this list short.
- "itinerary": exactly {req.days} objects, each with:
  - "day" (int),
  - "locality" (string): the neighborhood / quarter / corridor for that day (e.g. "Embarcadero & Ferry Building", "Mission / Valencia St", "North Beach & Chinatown edge"),
  - "plan" (array of ids): only ids from places/eats, ordered for a single-day walking tour in that locality.
- No duplicate ids across days.

Context:
{combined_context}

Output ONLY valid JSON inside the <final_answer> block. No markdown around the JSON."""

    try:
        print(">>> [ITINERARY GENERATION] Prompting LLM with Chain of Thought...")
        nodes = None
        for attempt in range(2):
            attempt_prompt = prompt
            if attempt == 1:
                attempt_prompt += (
                    "\n\nRETRY INSTRUCTIONS: Your previous answer likely had fake or placeholder names. "
                    "Regenerate with only specific real venues and locality-accurate heritage/art stops."
                )
            content = await _invoke_itinerary_model(attempt_prompt, itinerary_tier)
            print(">>> [ITINERARY GENERATION] Received response snippet:", content[:200])
            candidate = _extract_json_object(content)
            if not _itinerary_has_placeholder_names(candidate):
                nodes = candidate
                break
            nodes = candidate

        if nodes is None:
            raise ValueError("Unable to generate itinerary JSON.")

        seen_ids = set()
        for day in nodes.get("itinerary", []):
            unique_plan = []
            for pid in day.get("plan", []):
                if pid not in seen_ids:
                    unique_plan.append(pid)
                    seen_ids.add(pid)
            day["plan"] = unique_plan
        _normalize_eats_quota(nodes, max_ratio=0.25)

        nodes["_debug"] = {
            "tier": itinerary_tier,
            "provider_mode": provider_mode,
            "model_candidates": itinerary_candidates,
        }
        return nodes
    except Exception as e:
        import traceback

        print("JSON Synthesis Error:")
        print(traceback.format_exc())
        return {
            "places": [],
            "eats": [],
            "itinerary": [],
            "error": "Itinerary generation is temporarily unavailable. Please try again shortly.",
            "_debug": {
                "tier": itinerary_tier,
                "provider_mode": provider_mode,
                "model_candidates": itinerary_candidates,
            },
        }


@app.post("/api/holiday-briefing")
async def holiday_briefing(req: HolidayBriefingRequest):
    """
    Web search for trip-period weather, then LLM packing suggestions for Holiday Mode.
    """
    if req.city not in config.HERO_CITIES:
        return {
            "error": f"Only hero cities are supported: {', '.join(config.HERO_CITIES)}",
            "packing_advice": "",
            "web_context": "",
        }

    if req.start_date and req.start_date.strip():
        window = f"starting {req.start_date} for {req.days} day(s)"
    else:
        window = f"next {req.days} day(s) (no start date set — generic outlook)"

    try:
        print(f">>> [HOLIDAY BRIEFING] Fetching reliable weather for: {req.city}")
        web = get_weather.invoke({"city": req.city})
        search_q = f"get_weather({req.city})"
        print(">>> [HOLIDAY BRIEFING] Weather data:", str(web)[:200])
    except Exception as e:
        search_q = f"get_weather({req.city})"
        web = f"(weather unavailable: {e})"

    prompt = f"""You help student travelers pack light and smart.

Web search results (may be incomplete or from aggregators — treat as hints, not guarantees):
---
{str(web)[:4000]}
---

Trip: {req.city}. Travel window: {window}.

Write:
1) A short paragraph on likely weather during this window (say if uncertain).
2) A bullet list of clothing and gear (layers, footwear, rain/sun, daypack) suited to this city and length ({req.days} days).
Keep total under 260 words. Friendly, practical tone. No markdown # headers.
Output only the advice text the traveler reads — no editor notes, word counts, or "key edits" lists."""

    try:
        llm = get_chat_llm("small")
        resp = llm.invoke([HumanMessage(content=prompt)])
        advice = strip_editor_meta_from_user_text((resp.content or "").strip())
    except Exception as e:
        safe_err = _friendly_error_message(e, context="holiday")
        return {
            "error": safe_err,
            "packing_advice": "",
            "web_context": str(web)[:2000],
        }

    return {
        "packing_advice": advice,
        "web_context": str(web)[:2000],
        "search_query": search_q,
    }


@app.post("/api/walk-story")
async def walk_story(req: WalkStoryRequest):
    """
    Generate a short, vivid walk narration in the main assistant persona.
    This ensures spoken stop stories match the same persona style as chat.
    """
    city = (req.city or "").strip() or "this city"
    place = (req.place_title or "").strip()
    anecdote = (req.anecdote or "").strip()
    tier = _normalize_tier_value(req.llm_tier)
    if not place:
        return {"story": "", "error": "place_title is required"}

    prompt = f"""Create a spoken walking narration for a traveler standing near this place.
City: {city}
Place: {place}
Known local context:
{anecdote}

Requirements:
- 80-150 words.
- Output must be in English.
- Conversational and vivid (not robotic).
- The conversation could include a physical detail to notice right now, one historical/cultural detail and a local secret".
- Add a joke or light-hearted comment if it fits naturally, but don't force humor.
- Calculate the best next spot they should walk to from here, and if it is within a reasonable walking distance, mention it as a recommendation at the end.
- If there are no places to visit in walking distance, mention that fact and recommend another place near by they could visit by using transportation.
- Do not use markdown.
- Output only the spoken narration — no preambles, editor notes, or word counts.
"""
    try:
        llm = get_chat_llm(tier)
        out = await llm.ainvoke(
            [
                SystemMessage(content=build_system_prompt()),
                HumanMessage(content=prompt),
            ]
        )
        story = strip_editor_meta_from_user_text((out.content or "").strip())
        if not story:
            story = f"You're at {place}. {anecdote}".strip()
        return {"story": story, "model_tier": tier}
    except Exception as e:
        fallback = f"You're at {place}. {anecdote}".strip()
        return {"story": fallback, "model_tier": tier, "error": _friendly_error_message(e, context="walk_story")}


@app.get("/")
def read_root():
    return {
        "status": "WalkieTalkie backend",
        "hero_cities": list(config.HERO_CITIES),
        "system_prompt_preview": build_system_prompt()[:200] + "...",
    }


@app.post("/api/auth/signin")
def auth_signin(req: SignInRequest):
    uid = canonicalize_user_id(req.user_id)
    if not uid:
        return {"error": "user_id is required"}
    purged = purge_expired_sessions()
    if purged:
        logger.info("Purged expired sessions on signin | deleted=%s", purged)
    ensure_user(uid, display_name=req.display_name or uid)
    if req.budget is not None or req.dietary is not None or req.country is not None:
        update_user_preferences(uid, budget=req.budget, dietary=req.dietary, country=req.country)
    s = create_session(uid, ttl_hours=24)
    prefs = get_user_preferences(uid) or {}
    return {"ok": True, **s, "profile": prefs}


@app.get("/api/auth/me")
def auth_me(session_token: str):
    s = get_user_by_session(session_token)
    if not s:
        return {"ok": False, "error": "invalid_or_expired_session"}
    return {"ok": True, "user": s}


@app.post("/api/auth/logout")
def auth_logout(req: LogoutRequest):
    ok = revoke_session((req.session_token or "").strip())
    return {"ok": ok}


@app.post("/api/city/warmup")
def city_warmup(req: CityWarmupRequest):
    city = (req.city or "").strip()
    if city not in config.HERO_CITIES:
        return {"ok": False, "error": f"Unsupported city. Choose one of: {', '.join(config.HERO_CITIES)}"}
    _ensure_city_warmup_async(city)
    st = get_city_index_status(city)
    return {"ok": True, "city": city, "status": st or {"city": city, "status": "building"}}


@app.get("/api/city/status")
def city_status(city: str):
    city = (city or "").strip()
    if not city:
        return {"ok": False, "error": "city is required"}
    st = get_city_index_status(city)
    if not st:
        return {"ok": True, "city": city, "status": "missing"}
    fresh = int(time.time()) - int(st.get("updated_at") or 0) < _CITY_INDEX_TTL_SEC
    return {"ok": True, "city": city, **st, "fresh": fresh}


@app.patch("/api/user/profile")
def update_profile(req: UpdateProfileRequest):
    s = get_user_by_session(req.session_token)
    if not s:
        return {"ok": False, "error": "invalid_or_expired_session"}
    update_user_preferences(s["user_id"], budget=req.budget, dietary=req.dietary, country=req.country)
    prefs = get_user_preferences(s["user_id"]) or {}
    return {"ok": True, "profile": prefs}


@app.post("/api/user/visited")
def save_visited(req: VisitedPlaceRequest):
    s = get_user_by_session(req.session_token)
    if not s:
        return {"ok": False, "error": "invalid_or_expired_session"}
    msg = save_visited_place(s["user_id"], req.place_name, city=req.city)
    return {"ok": True, "message": msg}


@app.get("/api/chat/history")
def chat_history(session_token: str, city: str, limit: int = 100):
    s = get_user_by_session(session_token)
    if not s:
        return {"ok": False, "error": "invalid_or_expired_session", "history": []}
    rows = get_chat_history(s["user_id"], city, limit=limit)
    return {"ok": True, "history": rows}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "openrouter_base_url": config.openrouter_base_url(),
        "has_openrouter_key": bool(config.openrouter_api_key()),
        "embedding_backend": "openrouter" if config.OPENROUTER_EMBEDDING_MODEL else "ollama",
    }


@app.get("/api/qa/status")
def qa_status():
    """One-call smoke test for manual QA: embed dim, tiny chat, vector DB snippet."""
    out: dict = {
        "health": {
            "ok": True,
            "openrouter_base_url": config.openrouter_base_url(),
            "has_openrouter_key": bool(config.openrouter_api_key()),
            "embedding_backend": "openrouter" if config.OPENROUTER_EMBEDDING_MODEL else "ollama",
        },
        "models": {
            "small": config.SMALL_LLM_MODEL,
            "large": config.LARGE_LLM_MODEL,
            "embedding": config.OPENROUTER_EMBEDDING_MODEL or config.EMBEDDING_MODEL,
        },
        "hero_cities": list(config.HERO_CITIES),
    }
    try:
        from llm_factory import get_chat_llm, get_embedding_model

        emb = get_embedding_model()
        dim = len(emb.embed_query("San Francisco walking tour"))
        llm = get_chat_llm("small")
        r = llm.invoke("Reply with exactly: OK")
        chat = (r.content or "").strip()[:200]
        vec = search_local_history.invoke("Ferry Building San Francisco history")
        out["smoke"] = {
            "ok": True,
            "embed_dim": dim,
            "chat_reply": chat,
            "vector_preview": (vec or "")[:600],
            "vector_ok": "failed" not in (vec or "").lower() and len(vec or "") > 50,
        }
    except Exception as e:
        out["smoke"] = {"ok": False, "error": repr(e)}
    return out
