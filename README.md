# WalkieTalkie – An AI-Powered Walking Tour Companion

**WalkieTalkie** is an intelligent travel companion that creates personalized, voice-narrated walking tours in your current city. Using GPT-powered LLMs and real-time location data, it generates dynamic itineraries, tells local stories, and suggests nearby attractions—all delivered through natural speech synthesis.

## 🎯 Key Features

- **Dynamic Itinerary Generation**: AI-powered route planning based on your location and interests
- **Voice-Narrated Stories**: Natural language synthesis with multi-voice selection
- **Location-Triggered Content**: Automatic story unlocking as you move through the city
- **Multi-City Support**: Extensible city/location database (San Francisco, Kolkata, and more)
- **Offline-First Frontend**: Progressive Web App (PWA) with IndexedDB caching
- **Real-Time Weather & Events**: Integration with OpenWeatherMap and SerpAPI for contextual content

## 📋 Technology Stack

- **Backend**: Python 3.8+, FastAPI, LangChain, Chroma vector DB (SQLite)
- **Frontend**: React 19, Vite 7, PWA (offline support), IndexedDB
- **LLMs**: OpenRouter (primary), Ollama (fallback option)
- **APIs**: OpenWeatherMap, SerpAPI (optional), GPT/embeddings models

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** and **Node.js 16+** installed
- **API Key**: OpenRouter API key (free tier available at https://openrouter.ai)
- **Optional API Keys**: 
  - `OPENWEATHERMAP_API_KEY` (for weather integration)
  - `SERPAPI_API_KEY` (for event/web search)

### Setup (5 minutes)

#### 1. Clone & Navigate
```bash
git clone <repo-url>
cd WalkieTalkie
```

#### 2. Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# OR (macOS/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your API keys (see Configuration section below)
# At minimum: OPENROUTER_API_KEY=your_key_here
```

#### 3. Frontend Setup
```bash
cd ../walkie-talkie-app

npm install

# Start dev server (auto-opens http://localhost:5173)
npm run dev
```

#### 4. Start Backend API
```bash
# From backend/ directory (with venv activated)
uvicorn main:app --reload --port 8000
```

**That's it!** Frontend proxy automatically routes `/api/*` to `http://localhost:8000`.

## ⚙️ Configuration

### Required: API Keys

Edit `backend/.env` to provide:

```env
# OpenRouter (required) – get from https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-...

# Optional but recommended
OPENWEATHERMAP_API_KEY=your_key_here
SERPAPI_API_KEY=your_key_here
```

### Backend Environment Variables

Full documentation available in [backend/README.md](backend/README.md):

| Variable | Purpose | Default | Required |
|----------|---------|---------|----------|
| `OPENROUTER_API_KEY` | LLM & embeddings provider | — | ✅ Yes |
| `OPENROUTER_BASE_URL` | OpenRouter endpoint | `https://openrouter.ai/api/v1` | No |
| `LLM_MODEL` | Chat model | `meta-llama/llama-2-7b-chat` | No |
| `EMBEDDING_BACKEND` | Embeddings source | `ollama` | No |
| `OLLAMA_BASE_URL` | Ollama server | `http://localhost:11434` | No (if using Ollama) |
| `OPENWEATHERMAP_API_KEY` | Weather data | — | Optional |
| `SERPAPI_API_KEY` | Web search & events | — | Optional |

### Frontend Environment Variables

Edit `walkie-talkie-app/.env` (or `.env.local`):

```env
# Optional – defaults to http://127.0.0.1:8000
VITE_BACKEND_URL=http://127.0.0.1:8000
```

## 🔌 Port Mapping

| Service | Port | URL |
|---------|------|-----|
| Backend API | 8000 | `http://localhost:8000/api/*` |
| Frontend Dev | 5173 | `http://localhost:5173` |
| Ollama (optional) | 11434 | `http://localhost:11434` |

**Frontend automatically proxies** `/api/*` requests to the backend via Vite dev server config.

## 📦 First-Run Data Ingestion

Populate the vector database with city data:

```bash
cd backend
# With venv activated:
python ingest_data.py
```

This creates/updates the Chroma SQLite database in `backend/chroma_db/` with:
- City metadata and landmark descriptions
- Seed locations from `backend/data/*.txt`
- Embeddings for semantic search

## 🏃 Development Workflow

### Run All Services Locally

**Terminal 1 – Backend:**
```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
uvicorn main:app --reload --port 8000
```

**Terminal 2 – Frontend:**
```bash
cd walkie-talkie-app
npm run dev
```

Visit `http://localhost:5173` in your browser.

### Testing

#### Backend QA (multi-user auth/session isolation):
```bash
cd backend
python auth_isolation_qa.py
```

#### Frontend Build Verification:
```bash
cd walkie-talkie-app
npm run build  # Production build to dist/
```

## 📁 Project Structure

```
WalkieTalkie/
├── backend/                 # FastAPI server
│   ├── main.py             # Entry point, routes
│   ├── config.py           # Config & city definitions
│   ├── database.py         # SQLite + Chroma operations
│   ├── llm_factory.py      # LLM/embeddings initialization
│   ├── prompting.py        # System prompts & chat logic
│   ├── tools.py            # Weather, search, tool definitions
│   ├── ingest_data.py      # Populate vector DB
│   ├── requirements.txt    # Python dependencies
│   ├── .env.example        # Template for .env
│   └── chroma_db/          # SQLite vector store (auto-created)
│
├── walkie-talkie-app/       # React + Vite frontend
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── services/       # NarratorService (Web Speech API)
│   │   ├── hooks/          # useGeolocation hook
│   │   ├── utils/          # Geo calculations, story templating
│   │   └── db/             # IndexedDB operations
│   ├── vite.config.js      # Dev server + proxy config
│   ├── package.json        # npm dependencies
│   └── .env.example        # Template for .env
│
├── evaluation/             # Test & validation scripts
│   ├── run_eval.py         # Test harness
│   ├── queries.yaml        # Test cases
│   └── results/            # (ignored by git)
│
└── docs/                   # Additional documentation
```

## 🤝 Contributing

1. **Create a feature branch**: `git checkout -b feature/your-feature`
2. **Make changes** and test locally
3. **Verify backend tests**: `python backend/auth_isolation_qa.py`
4. **Build frontend**: `cd walkie-talkie-app && npm run build`
5. **Commit with clear messages** and push

## 🐛 Troubleshooting

### Frontend Can't Reach Backend
**Error**: `[vite] http proxy error: /api/chat — Error: connect ECONNREFUSED 127.0.0.1:8000`

**Solution**:
1. Verify backend is running: `curl http://localhost:8000/api/health`
2. Check `walkie-talkie-app/vite.config.js` has correct proxy target
3. Restart Vite dev server: `npm run dev`

### Missing API Key Error
**Error**: Backend responds with `missing OPENROUTER_API_KEY`

**Solution**:
1. Get free API key from https://openrouter.ai
2. Add to `backend/.env`: `OPENROUTER_API_KEY=sk-or-...`
3. Restart backend: `uvicorn main:app --reload --port 8000`

### Vector DB Issues
**Error**: Chroma DB errors on first run

**Solution**:
```bash
cd backend
rm -rf chroma_db/  # or rmdir /s chroma_db (Windows)
python ingest_data.py  # Rebuild
```

## 📖 Additional Docs

- **[Backend README](backend/README.md)** – Detailed API docs, models, embeddings
- **[Frontend README](walkie-talkie-app/README.md)** – Component architecture, PWA setup
- **[Prompting Notes](docs/PROMPTING_NOTES.md)** – LLM system prompts & tuning

## 📝 License

[Your license here]

---

**Questions?** Open an issue or contact the team. Happy walking! 🚶‍♂️
