"""
Dynamic + curated ingestion for city knowledge into ChromaDB.

Run from `backend/`:
  python ingest_data.py
"""
from __future__ import annotations

import os
import re
import hashlib
import requests
from bs4 import BeautifulSoup
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from llm_factory import get_embedding_model
from database import set_city_index_status

URLS_SF = [
    "https://49miles.com/2022/a-brief-history-of-san-francisco-everything-you-need-to-know/",
    "https://sfcityguides.org/tour/1840s-san-francisco-and-the-astonishing-legacy-of-americas-first-black-millionaire/",
    "https://sfcityguides.org/find-your-tour/",
]

KOLKATA_FILE = os.path.join(os.path.dirname(__file__), "data", "kolkata_seed.txt")
DB_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
COLLECTION_NAME = "local_stories"

QUERY_TEMPLATES = [
    "{city} history architecture culture overview",
    "{city} local art districts museums heritage",
    "{city} neighborhood history timeline",
]

BLOCKLIST_HINTS = (
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "tripadvisor.",
    "booking.com",
    "expedia.",
    "reddit.com",
    "youtube.com",
)

QUALITY_HINTS = (
    "history",
    "museum",
    "heritage",
    "culture",
    "architecture",
    "neighborhood",
    "district",
    "art",
)


def scrape_url(url: str) -> str:
    print(f"Scraping {url}...")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
        return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return ""


def _is_candidate_url_ok(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u.startswith("http"):
        return False
    if any(b in u for b in BLOCKLIST_HINTS):
        return False
    return True


def discover_city_sources(city: str, max_sources: int = 8) -> list[str]:
    wrapper = DuckDuckGoSearchAPIWrapper(max_results=8)
    seen = set()
    urls: list[str] = []
    for qtpl in QUERY_TEMPLATES:
        query = qtpl.format(city=city)
        try:
            results = wrapper.results(query, max_results=8)
        except Exception:
            continue
        for row in results:
            link = str(row.get("link") or "").strip()
            if not _is_candidate_url_ok(link):
                continue
            norm = link.rstrip("/")
            if norm in seen:
                continue
            seen.add(norm)
            urls.append(link)
            if len(urls) >= max_sources:
                return urls
    return urls


def _extract_readable_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _passes_quality_gate(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) < 900:
        return False
    return any(k in t for k in QUALITY_HINTS)


def _city_slug(city: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", city.lower()).strip("_")


def ingest_city(city: str, max_sources: int = 8) -> dict:
    city = (city or "").strip()
    if not city:
        raise ValueError("city is required")
    set_city_index_status(city, "building")

    if city == "San Francisco":
        source_urls = list(URLS_SF)
    else:
        source_urls = discover_city_sources(city, max_sources=max_sources)

    documents: list[dict] = []
    for url in source_urls:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            text = _extract_readable_text(r.text)
            if not _passes_quality_gate(text):
                continue
            documents.append({"text": text, "source": url, "city": city})
        except Exception:
            continue

    # Keep Kolkata local seed as a stable low-cost baseline.
    if city == "Kolkata" and os.path.isfile(KOLKATA_FILE):
        with open(KOLKATA_FILE, encoding="utf-8") as f:
            ktxt = f.read().strip()
        if ktxt:
            documents.append({"text": ktxt, "source": "kolkata_seed_local", "city": city})

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks: list[str] = []
    metadata: list[dict] = []
    for doc in documents:
        splits = splitter.split_text(doc["text"])
        chunks.extend(splits)
        metadata.extend([{"source": doc["source"], "city": doc["city"]} for _ in splits])

    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    emb_model = get_embedding_model()
    city_key = _city_slug(city)

    # Remove prior city chunks before refresh.
    try:
        existing = collection.get(where={"city": city}, include=[])
        ids = existing.get("ids") or []
        if ids:
            collection.delete(ids=ids)
    except Exception:
        pass

    inserted = 0
    for i, chunk in enumerate(chunks):
        try:
            emb = emb_model.embed_query(chunk)
            digest = hashlib.sha1(f"{city}|{metadata[i]['source']}|{i}|{chunk[:120]}".encode("utf-8")).hexdigest()[:16]
            cid = f"{city_key}_{digest}_{i}"
            collection.add(
                embeddings=[emb],
                documents=[chunk],
                metadatas=[metadata[i]],
                ids=[cid],
            )
            inserted += 1
        except Exception:
            continue

    status = "ready" if inserted > 0 else "failed"
    err = None if inserted > 0 else "No usable sources/chunks for city"
    set_city_index_status(city, status, source_count=len(documents), chunk_count=inserted, error=err)
    return {
        "city": city,
        "status": status,
        "source_count": len(documents),
        "chunk_count": inserted,
        "sources": [d["source"] for d in documents],
    }


def main():
    import config

    config.assert_api_config()

    for city in ("San Francisco", "Kolkata"):
        print(f"Ingesting city: {city}")
        result = ingest_city(city)
        print(result)


if __name__ == "__main__":
    main()
