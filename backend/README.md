# WalkieTalkie

An AI-powered virtual walking tour guide with story retrieval, and multi-user session management.

## 🎯 Overview

**WalkieTalkie Backend** serves as the intelligence engine:
- **LLM Integration**: OpenRouter + optional Ollama for open-source models
- **Vector Database**: Chroma (SQLite) for semantic story/location search
- **Multi-User Sessions**: SQLite profile persistence, auth isolation, personalization
- **Real-Time Tools**: Weather, web search, calendar events, location recommendations
- **Supported Cities**: San Francisco, Kolkata, and extensible via configuration

## Supported Models

### Recommended Free/Sponsored Tiers (OpenRouter)

| Model | Size | Purpose | Tier |
|-------|------|---------|------|
| `openai/gpt-oss-20b:free` | Small | Chat, routing | Free tier |
| `nvidia/nemotron-3-super-120b-a12b:free` | Large | Complex reasoning | Free tier |
| `nvidia/nemotron-nano-12b-v2-vl:free` | Vision | Image understanding | Free tier |

### Embeddings Options

- **OpenRouter**: Set `OPENROUTER_EMBEDDING_MODEL` (e.g., `openai/text-embedding-3-small`)

## Setup

### Prerequisites
- Python 3.8+
- OpenRouter API key (free from https://openrouter.ai/keys)
- Optional: Ollama (for local embeddings/fallback LLM)

### Installation

#### 1. Create Virtual Environment
```bash
cd backend
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate
```

#### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 3. Configure Environment
```bash
cp .env.example .env
```

Edit `.env` and provide:

```env
# REQUIRED
OPENROUTER_API_KEY=sk-or-v1-...  # Get from https://openrouter.ai/keys

# Model Selection (defaults shown)
LLM_MODEL=openai/gpt-oss-20b:free
EMBEDDING_BACKEND=ollama              # or "openrouter"
OPENROUTER_EMBEDDING_MODEL=          # Leave blank if using Ollama

# Optional APIs
OPENWEATHERMAP_API_KEY=               # Weather integration
SERPAPI_API_KEY=                      # Web search & events

# Ollama (only if EMBEDDING_BACKEND=ollama)
OLLAMA_BASE_URL=http://localhost:11434
```

### 4. Ingest City Data
Populate the vector database with curated stories and landmarks:

```bash
python ingest_data.py
```

This:
- Creates `chroma_db/` SQLite database
- Ingests seed data from `backend/data/` (e.g., Kolkata landmarks)
- Generates embeddings for semantic search
- Creates indices for fast retrieval

**Important**: If you change embedding models, delete `chroma_db/` before re-running to ensure vector dimensions stay consistent.

## Running the Server

```bash
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

### Health Check
```bash
curl http://localhost:8000/api/health
```

**Response** (example):
```json
{
  "ok": true,
  "openrouter_base_url": "https://openrouter.ai/api/v1",
  "has_openrouter_key": true,
  "embedding_backend": "ollama"
}
```

## API Endpoints

### Core Routes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Server status & config |
| `/api/qa/status` | GET | LLM + embeddings health check |
| `/api/chat` | POST | Chat with itinerary assistant |
| `/api/itinerary` | GET | Fetch or generate walking tour |
| `/api/nearby` | GET | Find stories near location |

### Request/Response Examples

**Generate Itinerary**:
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Create a 2-hour walking tour of San Francisco starting from Market Street"
  }'
```

**Get Nearby Stories**:
```bash
curl "http://localhost:8000/api/nearby?lat=37.7749&lon=-122.4194&city=San%20Francisco&radius=500"
```

## Multi-User Session Management

### Profile Persistence
- Per-user SQLite records: visited places, preferences, budget
- Auth isolation: each user session gets isolated context
- Tools for personalization: `record_visited_place`, `update_profile`

### Testing Auth Isolation
```bash
python auth_isolation_qa.py
```

Tests:
- User sign-in & profile creation
- Profile updates (budget, preferences)
- Visited place recording
- Session logout & data cleanup

## Vector Database (Chroma)

### Location
`backend/chroma_db/chroma.sqlite3`

### Collections
- `stories` — narrative content for locations
- `landmarks` — place metadata and descriptions

### Embeddings Lifecycle

**With OpenRouter**:
```python
EMBEDDING_BACKEND=openrouter
OPENROUTER_EMBEDDING_MODEL=openai/text-embedding-3-small
```
→ Embeddings generated on ingest, queried via OpenRouter

**With Ollama** (default):
```python
EMBEDDING_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
```
→ Requires local Ollama running; pulls `nomic-embed-text:latest` automatically

### Rebuilding the DB
```bash
rm -rf chroma_db/
python ingest_data.py  # Regenerate with current embeddings
```

## Troubleshooting

### Error: "missing OPENROUTER_API_KEY"
**Cause**: Environment variable not set  
**Fix**: 
1. Get key from https://openrouter.ai/keys
2. Add to `.env`: `OPENROUTER_API_KEY=sk-or-...`
3. Restart server

### Error: "Ollama connection refused"
**Cause**: `EMBEDDING_BACKEND=ollama` but Ollama not running  
**Fix**:
1. Start Ollama: `ollama serve` (on port 11434)
2. OR switch to OpenRouter embeddings in `.env`

### Error: "Vector dimension mismatch"
**Cause**: Changed embedding model without rebuilding DB  
**Fix**:
```bash
rm -rf chroma_db/
python ingest_data.py
```

### Frontend Proxy Errors
**Cause**: Backend not reachable from frontend  
**Fix**:
1. Verify backend running: `curl http://localhost:8000/api/health`
2. Check frontend Vite config: `walkie-talkie-app/vite.config.js` should proxy to `8000`
3. Restart frontend dev server

## File Structure

```
backend/
├── main.py              # FastAPI app, routes
├── config.py            # Hero cities, model defaults, config loader
├── database.py          # SQLite & Chroma operations
├── llm_factory.py       # LLM/embeddings initialization
├── prompting.py         # System prompts, chat logic
├── tools.py             # Weather, search, tool definitions
├── ingest_data.py       # Populate vector DB
├── auth_isolation_qa.py # Multi-user QA script
├── requirements.txt     # Python dependencies
├── .env.example         # Template (copy to .env)
├── data/                # Seed data
│   └── kolkata_seed.txt # Kolkata landmarks
└── chroma_db/           # Vector store (auto-created)
    ├── chroma.sqlite3   # Main DB file
    └── [collection dirs]
```

## Configuration Reference

### Backend Environment Variables

```env
# REQUIRED
OPENROUTER_API_KEY=sk-or-v1-...

# Model Selection
LLM_MODEL=openai/gpt-oss-20b:free          # Main chat model
EMBEDDING_BACKEND=ollama                   # or "openrouter"
OPENROUTER_EMBEDDING_MODEL=                # Set if EMBEDDING_BACKEND=openrouter
OLLAMA_BASE_URL=http://localhost:11434    # Ollama server URL

# APIs (optional)
OPENWEATHERMAP_API_KEY=                    # Weather integration
SERPAPI_API_KEY=                           # Web search & events
```

### City Support

Defined in `config.HERO_CITIES`:
- `san-francisco` (US)
- `kolkata` (India)
- Extensible: add new cities to config and provide seed data

## See Also

- **[Root README](../README.md)** – Full project overview
- **[Frontend README](../walkie-talkie-app/README.md)** – React/PWA setup
- **[Prompting Notes](../docs/PROMPTING_NOTES.md)** – LLM system prompts

## Development

### Running Tests
```bash
python auth_isolation_qa.py  # Multi-user auth tests
```

### Code Style
- Follow PEP 8
- Use type hints where practical
- Document complex functions with docstrings