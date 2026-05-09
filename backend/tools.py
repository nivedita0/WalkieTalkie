from langchain.tools import tool
import chromadb
import os
import logging
import time
from io import BytesIO
import requests
from bs4 import BeautifulSoup
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_community.tools import DuckDuckGoSearchRun

import config
from database import get_user_preferences, save_visited_place
from llm_factory import get_embedding_model

db_path = os.path.join(os.path.dirname(__file__), "chroma_db")
logger = logging.getLogger("walkietalkie.tools")


def _upload_image_to_public_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Upload image bytes to a temporary public host and return a direct URL.
    Primary: 0x0.st (plain text URL)
    Fallback: tmpfiles.org (JSON page URL transformed to /dl/ direct URL)
    """
    # Primary: 0x0.st
    try:
        resp = requests.post(
            "https://0x0.st",
            files={"file": ("image.jpg", image_bytes, mime_type)},
            timeout=25,
        )
        resp.raise_for_status()
        url = (resp.text or "").strip()
        if url.startswith("https://"):
            logger.info("Uploaded image to 0x0.st | url=%s", url)
            return url
        logger.warning("0x0.st returned unexpected body: %s", (resp.text or "")[:300])
    except Exception as e:
        logger.warning("0x0.st upload failed: %s", e)

    # Fallback: tmpfiles.org
    try:
        resp = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": ("image.jpg", image_bytes, mime_type)},
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        page_url = str(((data.get("data") or {}).get("url") or "")).strip()
        if page_url and "tmpfiles.org/" in page_url:
            direct_url = page_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
            if direct_url.startswith("http://"):
                direct_url = "https://" + direct_url[len("http://") :]
            logger.info("Uploaded image to tmpfiles.org | url=%s", direct_url)
            return direct_url
        raise ValueError(f"tmpfiles.org response missing usable URL: {str(data)[:300]}")
    except Exception as e:
        raise RuntimeError(f"All public upload providers failed: {e}")


def _serpapi_get_with_retry(params: dict, retries: int = 2, base_delay_sec: float = 1.5) -> requests.Response:
    """
    GET SerpAPI with retry/backoff for 429 rate-limit responses.
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=25,
            )
            if resp.status_code == 429 and attempt < retries:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_sec = max(base_delay_sec, float(retry_after))
                    except Exception:
                        sleep_sec = base_delay_sec * (2 ** (attempt - 1))
                else:
                    sleep_sec = base_delay_sec * (2 ** (attempt - 1))
                logger.warning(
                    "SerpAPI rate-limited (429) | attempt=%s/%s | sleeping %.2fs",
                    attempt,
                    retries,
                    sleep_sec,
                )
                time.sleep(sleep_sec)
                continue
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            last_exc = e
            if attempt < retries and getattr(e.response, "status_code", None) == 429:
                sleep_sec = base_delay_sec * (2 ** (attempt - 1))
                logger.warning(
                    "SerpAPI HTTP 429 on exception | attempt=%s/%s | sleeping %.2fs",
                    attempt,
                    retries,
                    sleep_sec,
                )
                time.sleep(sleep_sec)
                continue
            raise
        except Exception as e:
            last_exc = e
            if attempt < retries:
                sleep_sec = base_delay_sec * (2 ** (attempt - 1))
                logger.warning(
                    "SerpAPI transient error | attempt=%s/%s | sleeping %.2fs | err=%s",
                    attempt,
                    retries,
                    sleep_sec,
                    e,
                )
                time.sleep(sleep_sec)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("SerpAPI request failed without specific exception")


def serpapi_google_lens_lookup(image_bytes: bytes, city: str = "", max_results: int = 5) -> dict:
    """
    Reverse-image lookup via SerpAPI Google Reverse Image.
    Returns normalized top matches and knowledge graph if available.
    """
    api_key = config.serpapi_api_key()
    if not api_key:
        logger.warning("SERPAPI_API_KEY missing; cannot perform reverse image lookup")
        return {"ok": False, "error": "SERPAPI_API_KEY not configured", "matches": []}
    try:
        from PIL import Image

        # 1) Resize image to max dimension 1024 for faster and safer downstream requests.
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")
        max_dim = max(img.size)
        if max_dim > 1024:
            scale = 1024 / float(max_dim)
            new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
            img = img.resize(new_size, Image.LANCZOS)
        out_buf = BytesIO()
        img.save(out_buf, format="JPEG", quality=88, optimize=True)
        resized_bytes = out_buf.getvalue()

        logger.info(
            "SerpAPI Lens lookup start | city=%s bytes_in=%s bytes_resized=%s max_results=%s",
            city,
            len(image_bytes or b""),
            len(resized_bytes or b""),
            max_results,
        )

        # 2) Upload image to public temp URL host.
        image_url = _upload_image_to_public_url(resized_bytes, mime_type="image/jpeg")
        payload = {}
        serpapi_engine_used = ""
        logger.info("Public image URL ready | url=%s", image_url)
        serpapi_params = {
            "engine": "google_lens",
            "url": image_url,
            "api_key": api_key,
            "hl": "en",
            "gl": "us",
        }
        resp = _serpapi_get_with_retry(serpapi_params, retries=2, base_delay_sec=1.5)
        try:
            payload = resp.json()
        except Exception:
            logger.error(
                "SerpAPI non-JSON response (URL mode) | status=%s body_preview=%s",
                resp.status_code,
                (resp.text or "")[:800],
            )
            payload = {}
        serpapi_engine_used = "google_lens_url"

        visual_matches = (
            payload.get("visual_matches")
            or payload.get("image_results")
            or payload.get("inline_images")
            or payload.get("organic_results")
            or []
        )
        knowledge_graph = payload.get("knowledge_graph") or {}

        matches = []
        for item in visual_matches[:max_results]:
            title = str(item.get("title", "")).strip()
            link = str(item.get("link", "")).strip()
            snippet = str(item.get("snippet", "") or item.get("source", "") or "").strip()
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."
            if not (title or link):
                continue
            matches.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "link": link,
                }
            )

        # Optional city filter score boost for caller-side ranking.
        city_l = (city or "").strip().lower()
        if city_l:
            for m in matches:
                hay = f"{m.get('title','')} {m.get('snippet','')} {m.get('link','')}".lower()
                m["city_hint_match"] = city_l in hay

        result = {
            "ok": True,
            "error": "",
            "matches": matches,
            "knowledge_graph": knowledge_graph,
            "search_metadata": payload.get("search_metadata", {}),
            "image_url": image_url,
            "engine_used": serpapi_engine_used,
        }
        logger.info("SerpAPI Lens lookup complete | matches=%s has_kg=%s", len(matches), bool(knowledge_graph))
        if matches:
            logger.debug("Top image match: %s", str(matches[0])[:500])
        return result
    except Exception as e:
        logger.exception("SerpAPI Google Lens lookup failed: %s", e)
        return {"ok": False, "error": f"SerpAPI Google Lens failed: {e}", "matches": []}


@tool
def search_local_history(query: str) -> str:
    """Useful to search for local history, anecdotes, and context about a neighborhood or landmark (San Francisco & Kolkata curated stories)."""
    try:
        client = chromadb.PersistentClient(path=db_path)
        collection = client.get_collection("local_stories")
        embeddings_model = get_embedding_model()
        emb = embeddings_model.embed_query(query)
        q = (query or "").lower()
        city = None
        for c in (
            "san francisco",
            "kolkata",
            "new york",
            "boston",
            "chicago",
            "los angeles",
            "miami",
            "philadelphia",
            "seattle",
            "washington dc",
        ):
            if c in q:
                city = c.title() if c != "washington dc" else "Washington DC"
                break

        if city:
            results = collection.query(query_embeddings=[emb], n_results=3, where={"city": city})
            docs = (results.get("documents") or [[]])[0]
            if not docs:
                results = collection.query(query_embeddings=[emb], n_results=2)
        else:
            results = collection.query(query_embeddings=[emb], n_results=2)

        snippets = []
        for doc in (results.get("documents") or [[]])[0]:
            snippets.append(doc)
        if not snippets:
            return "No local history cache available for that city yet. Use search_web for live context."
        return "\n\n".join(snippets)
    except Exception as e:
        return f"Vector DB query failed ({e}). Rely on search_web or general knowledge with clear uncertainty."


@tool
def fetch_user_profile(user_id: str) -> str:
    """Fetch the user's budget, dietary restrictions, and home country from the database."""
    prefs = get_user_preferences(user_id)
    if prefs:
        return f"User Profile -> Budget: ${prefs['budget']}/day, Diet: {prefs['dietary']}, Home Country: {prefs['country']}"
    return "No user profile found. Default to budget-conscious student."


@tool
def record_visited_place(user_id: str, place_name: str, city: str = "") -> str:
    """Save a place the user has visited to their Explorer Profile database."""
    return save_visited_place(user_id, place_name, city=city or None)


@tool
def search_web(query: str) -> str:
    """Useful to search the internet for live facts, hours, weather, transit, tickets, visas, or unknown places."""
    try:
        logger.info("Web search start | query=%s", query[:300])
        search = DuckDuckGoSearchRun()
        out = search.run(query)
        logger.info("Web search complete | response_chars=%s", len(out or ""))
        logger.debug("Web search preview: %s", (out or "")[:1200])
        return out
    except Exception as e:
        logger.exception("Web search failed: %s", e)
        return f"Web search failed: {e}"


@tool
def get_weather(city: str) -> str:
    """Fetch real-time weather for any city using OpenWeatherMap.
    Returns temperature (°F and °C), feels-like, humidity, wind speed, and a short condition description.
    Use this whenever the user asks about weather, rain, temperature, what to wear, or packing for climate.
    Input: city name (e.g. 'San Francisco', 'New York', 'Boston').
    """
    api_key = config.openweathermap_api_key()
    if not api_key:
        return (
            "Weather tool is unavailable (OPENWEATHERMAP_API_KEY not set). "
            "Please check https://openweathermap.org/current for conditions."
        )
    try:
        # Step 1: geocode city → lat/lon via /geo/1.0/direct
        geo_url = "https://api.openweathermap.org/geo/1.0/direct"
        geo_resp = requests.get(
            geo_url,
            params={"q": city, "limit": 1, "appid": api_key},
            timeout=8,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
        if not geo_data:
            return f"Could not geocode '{city}'. Try a different spelling."
        lat, lon = geo_data[0]["lat"], geo_data[0]["lon"]
        resolved_name = geo_data[0].get("name", city)
        country = geo_data[0].get("country", "")

        # Step 2: current weather via /data/2.5/weather (units=imperial for °F)
        wx_url = "https://api.openweathermap.org/data/2.5/weather"
        wx_resp = requests.get(
            wx_url,
            params={"lat": lat, "lon": lon, "units": "imperial", "appid": api_key},
            timeout=8,
        )
        wx_resp.raise_for_status()
        d = wx_resp.json()

        temp_f = d["main"]["temp"]
        temp_c = round((temp_f - 32) * 5 / 9, 1)
        feels_f = d["main"]["feels_like"]
        feels_c = round((feels_f - 32) * 5 / 9, 1)
        humidity = d["main"]["humidity"]
        wind_mph = d["wind"]["speed"]
        wind_kph = round(wind_mph * 1.609, 1)
        desc = d["weather"][0]["description"].capitalize()
        visibility_m = d.get("visibility", None)
        visibility_str = f", visibility {round(visibility_m / 1000, 1)} km" if visibility_m else ""

        return (
            f"Current weather in {resolved_name}, {country}: {desc}. "
            f"Temp {temp_f:.1f}°F ({temp_c}°C), feels like {feels_f:.1f}°F ({feels_c}°C). "
            f"Humidity {humidity}%, wind {wind_mph:.1f} mph ({wind_kph} km/h){visibility_str}."
        )
    except requests.HTTPError as e:
        return f"OpenWeatherMap API error ({e.response.status_code}): {e}"
    except Exception as e:
        return f"Weather lookup failed: {e}"


@tool
def scrape_static_history(city: str) -> str:
    """Scrapes static history pages for itinerary synthesis (hero cities)."""
    try:
        wrapper = DuckDuckGoSearchAPIWrapper(max_results=3)
        results = wrapper.results(f"history timeless hidden gems architectural monuments {city}", max_results=3)

        combined_data = []
        for res in results:
            url = res.get("link")
            snippet = res.get("snippet", "")
            if url:
                try:
                    headers = {"User-Agent": "Mozilla/5.0"}
                    resp = requests.get(url, headers=headers, timeout=4)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    text = " ".join([p.get_text() for p in soup.find_all("p")])
                    content = text[:1500] if text else snippet
                except Exception:
                    content = snippet
                combined_data.append(f"Source: {url}\nContent: {content}")

        return "\n\n".join(combined_data)
    except Exception as e:
        return f"Static scraping failed: {e}"


@tool
def scrape_live_context(city: str, date_range: str) -> str:
    """Scrapes real-time web context for weather, festivals, and events."""
    try:
        wrapper = DuckDuckGoSearchAPIWrapper(max_results=3)
        results = wrapper.results(f"local events festivals weather {city} {date_range}", max_results=3)

        combined_data = ["LIVE CONTEXT:"]
        for res in results:
            snippet = res.get("snippet", "")
            if snippet:
                combined_data.append(snippet)

        return "\n".join(combined_data)
    except Exception as e:
        return f"Live scraping failed: {e}"
