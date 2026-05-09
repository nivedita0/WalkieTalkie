# WalkieTalkie Frontend

React 19 + Vite 7 PWA providing an offline-first, voice-guided walking tour companion.

## 🎯 Overview

**WalkieTalkie Frontend** is a Progressive Web App (PWA) that:
- Displays real-time walking tours from the backend API
- Uses Web Speech Synthesis for voice narration
- Tracks user location via Geolocation API
- Caches content locally with IndexedDB for offline support
- Adapts to mobile & desktop screens

## 📋 Tech Stack

- **Framework**: React 19.2.0
- **Build Tool**: Vite 7.3.1 with Hot Module Reloading (HMR)
- **PWA**: vite-plugin-pwa for offline support
- **Storage**: IndexedDB for client-side caching
- **Styling**: CSS modules (see `src/index.css`)
- **Package Manager**: npm

## 🚀 Setup

### Prerequisites
- Node.js 16+ and npm installed
- Backend API running on `http://localhost:8000` (or set via `VITE_BACKEND_URL`)

### Installation

#### 1. Install Dependencies
```bash
cd walkie-talkie-app
npm install
```

#### 2. Configure Environment (Optional)
```bash
cp .env.example .env
```

Edit `.env` to customize backend URL:

```env
# Optional – defaults to http://127.0.0.1:8000
VITE_BACKEND_URL=http://127.0.0.1:8000
```

#### 3. Start Dev Server
```bash
npm run dev
```

The app will open at `http://localhost:5173` with HMR enabled.

## 📁 Project Structure

```
walkie-talkie-app/
├── src/
│   ├── components/
│   │   ├── SpatialTrigger.jsx       # GPS-based story unlocking
│   │   └── [other components]
│   ├── services/
│   │   └── NarratorService.js       # Web Speech Synthesis wrapper
│   ├── hooks/
│   │   └── useGeolocation.js        # Custom geolocation hook
│   ├── utils/
│   │   ├── geo.js                   # Distance calculations
│   │   └── storyTemplating.js       # Story formatting
│   ├── db/
│   │   └── db.js                    # IndexedDB operations
│   ├── data/
│   │   └── [static data]
│   ├── App.jsx                      # Root component
│   ├── main.jsx                     # Entry point
│   └── index.css                    # Global styles
├── public/
│   └── [static assets]
├── vite.config.js                   # Dev server & proxy config
├── package.json                     # Dependencies & scripts
├── index.html                       # HTML entry point
├── eslint.config.js                 # Linting rules
└── .env.example                     # Environment template
```

## 🔌 Backend Integration

### Proxy Configuration

The Vite dev server automatically proxies `/api/*` requests to the backend:

**vite.config.js**:
```javascript
server: {
  proxy: {
    '/api': {
      target: env.VITE_BACKEND_URL || 'http://127.0.0.1:8000',
      changeOrigin: true,
    }
  }
}
```

This means frontend code can use relative paths:
```javascript
// Automatically routed to http://localhost:8000/api/chat
fetch('/api/chat', { method: 'POST', body: JSON.stringify(...) })
```

### API Communication

Typical flow:
1. User initiates tour generation
2. Frontend calls `POST /api/chat` with preferences
3. Backend returns itinerary
4. Frontend caches in IndexedDB via `db.saveItinerary()`
5. NarratorService reads stories aloud as user moves

## 🎙️ Voice Narration

### NarratorService

Wraps the Web Speech Synthesis API with:
- Multi-language voice selection (English-only by default)
- Configurable speech rate, pitch, volume
- Fallback to system default voice

**Usage**:
```javascript
import { NarratorService } from './services/NarratorService';

const narrator = new NarratorService();
narrator.speak("Welcome to San Francisco!", {
  rate: 1.0,
  pitch: 1.0,
  lang: 'en-US'
});

// Cancel if needed
narrator.cancel();
```

## 📍 Location Tracking

### useGeolocation Hook

Custom React hook for real-time location:

```javascript
import { useGeolocation } from './hooks/useGeolocation';

function TourComponent() {
  const { coords, error, isLoading } = useGeolocation();
  
  if (error) return <div>Enable location to continue</div>;
  if (isLoading) return <div>Loading location...</div>;
  
  return <div>Lat: {coords.latitude}, Lon: {coords.longitude}</div>;
}
```

**Permissions**: Browser requests location access on first use. Requires HTTPS in production (HTTP ok for localhost dev).

### SpatialTrigger Component

Unlocks stories when user is within `radiusMeters` of a location:

```jsx
<SpatialTrigger
  targetLat={37.7749}
  targetLon={-122.4194}
  radiusMeters={100}
  onTrigger={() => playStory()}
/>
```

## 💾 IndexedDB Caching

### db.js API

```javascript
import * as db from './db/db.js';

// Save itinerary for offline access
await db.saveItinerary(cityName, itinerary);

// Retrieve cached data
const cached = await db.fetchCachedItinerary(cityName);

// Clear cache
await db.clearItineraryCache();
```

**Benefits**:
- App works offline after first load
- Faster subsequent loads (cached stories)
- Reduced server requests

## 🏗️ Building for Production

### Build
```bash
npm run build
```

Creates optimized production bundle in `dist/`:
- Minified JavaScript/CSS
- Code splitting for faster loads
- PWA manifest for installability

### Preview Production Build
```bash
npm run preview
```

Serves `dist/` locally to test production build.

## 🧹 Code Quality

### Lint
```bash
npm run lint
```

Checks code against ESLint rules (see `eslint.config.js`).

## 🐛 Troubleshooting

### Frontend Can't Reach Backend
**Error**: `Failed to fetch /api/chat` or `connect ECONNREFUSED 127.0.0.1:8000`

**Cause**: Backend not running or proxy misconfigured

**Fix**:
1. Start backend: `cd backend && uvicorn main:app --reload --port 8000`
2. Check `vite.config.js` proxy target (should be `8000`)
3. Restart dev server: `npm run dev`
4. Verify via browser console: `fetch('/api/health').then(r => r.json())`

### Geolocation Not Working
**Error**: "Location unavailable" or permission denied

**Cause**: Browser permission or HTTPS required in production

**Fix**:
1. Check browser permissions (click lock icon in URL bar)
2. Allow location access
3. For production: ensure HTTPS is enabled

### Build Fails with Module Errors
**Error**: `SyntaxError` or module not found

**Fix**:
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
npm run build
```

### PWA Not Installing
**Cause**: Web manifest or service worker issues

**Fix**:
1. Ensure `npm run build` completes without errors
2. Check DevTools → Application → Manifest (should be valid)
3. Reload page and try "Install app" prompt

## 🔧 Configuration

### Environment Variables

**File**: `.env` (or `.env.local`)

```env
# Backend API URL (default: http://127.0.0.1:8000)
VITE_BACKEND_URL=http://127.0.0.1:8000

# Vite debug mode (optional)
DEBUG=walkie-talkie:*
```

### Vite Config

Edit `vite.config.js` to:
- Change proxy target
- Adjust HMR settings for remote dev
- Enable/disable PWA features
- Modify output directory (`dist/`)

## 📖 See Also

- **[Root README](../README.md)** – Full project overview
- **[Backend README](../backend/README.md)** – API & LLM setup
- **[Prompting Notes](../docs/PROMPTING_NOTES.md)** – Story generation

## 🤝 Contributing

1. Create a feature branch
2. Make changes locally (`npm run dev` to test)
3. Run linter: `npm run lint`
4. Test build: `npm run build`
5. Commit & push

## 📝 Development Tips

- **Fast Refresh**: Edits to `.jsx` files auto-reload without losing state
- **DevTools**: Use React DevTools browser extension to inspect component hierarchy
- **Network tab**: Monitor API calls to backend (look for `/api/...` requests)
- **Console**: Check for JavaScript errors or console logs from NarratorService

---

**Questions?** Check the troubleshooting section or reach out to the team.
