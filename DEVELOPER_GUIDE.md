# 🎬 SpillTheReel — Developer Guide (Branch: `STRv1`)

> **SpillTheReel** is an AI-powered "second brain" for Instagram Reels. Users paste a Reel URL, the backend downloads its audio, transcribes it using Whisper, and stores the knowledge in a graph database. Users can then ask natural-language questions and get intelligent answers grounded in everything they've ever saved.

---

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [Repository Structure](#repository-structure)
- [Technology Stack](#technology-stack)
- [Data Flow — How It Works](#data-flow--how-it-works)
- [Backend Deep Dive](#backend-deep-dive)
  - [Pipeline Breakdown](#pipeline-breakdown)
  - [API Endpoints](#api-endpoints)
  - [Configuration & Environment Variables](#configuration--environment-variables)
  - [External Services](#external-services)
- [Frontend Deep Dive](#frontend-deep-dive)
  - [Component Architecture](#component-architecture)
  - [Backend Connectivity](#backend-connectivity)
  - [UI / UX](#ui--ux)
- [Getting Started — Local Setup](#getting-started--local-setup)
  - [Prerequisites](#prerequisites)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
  - [Connecting Frontend ↔ Backend](#connecting-frontend--backend)
- [Current Limitations & Known Issues](#current-limitations--known-issues)
- [Where To Go From Here — Contribution Ideas](#where-to-go-from-here--contribution-ideas)
- [Commit History](#commit-history)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER (Mobile / Web)                      │
│                   React Native (Expo) Frontend                  │
│                                                                 │
│   ┌───────────────┐              ┌──────────────────────────┐   │
│   │ Paste Reel URL│──── POST ───▶│  /ingest                 │   │
│   └───────────────┘              │  (Background Processing) │   │
│                                  └──────────┬───────────────┘   │
│   ┌───────────────┐              ┌──────────▼───────────────┐   │
│   │ Ask a Question│──── GET ────▶│  /chat?q=...             │   │
│   └───────────────┘              │  (Knowledge Retrieval)   │   │
│                                  └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                │
                   ┌────────────▼────────────┐
                   │   FastAPI Backend        │
                   │   (Python, main.py)      │
                   │                          │
                   │  yt-dlp → Whisper → Cognee│
                   └──┬──────────┬──────────┬─┘
                      │          │          │
              ┌───────▼──┐ ┌────▼────┐ ┌───▼──────┐
              │  Groq API │ │ Neo4j   │ │ LanceDB  │
              │ (Whisper) │ │(Graph)  │ │(Vectors) │
              └──────────┘ └─────────┘ └──────────┘
```

---

## Repository Structure

```
STR_v1/
├── backend/
│   ├── main.py              # FastAPI app — the entire backend in one file
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Template for environment variables
│   └── .gitignore           # Ignores venv/, __pycache__/, .env
│
├── frontend/
│   ├── App.js               # Main (and only) React Native component
│   ├── index.js             # Expo entry point — registers App
│   ├── package.json         # JS dependencies & scripts
│   ├── package-lock.json    # Locked dependency tree
│   ├── app.json             # Expo configuration (name, icons, scheme)
│   ├── assets/              # App icons (icon.png, favicon.png, splash, etc.)
│   ├── AGENTS.md            # Notes on Expo SDK version (v57)
│   ├── CLAUDE.md            # Points to AGENTS.md
│   ├── LICENSE              # MIT License
│   └── .gitignore           # Ignores node_modules/, .expo/, native builds
│
└── DEVELOPER_GUIDE.md       # ← You are here
```

> **Key Observation:** This is an MVP/prototype — the backend is a single `main.py` file and the frontend is a single `App.js` file. There are no multi-file architectures, routers, or component breakdowns yet.

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React Native + Expo (SDK 57) | Cross-platform mobile & web UI |
| **Backend** | FastAPI (Python) | REST API server |
| **Audio Download** | yt-dlp | Downloads audio from Instagram Reel URLs |
| **Transcription** | Groq API (Whisper Large v3) | Speech-to-text on downloaded audio |
| **Knowledge Graph** | Cognee + Neo4j AuraDB | Extracts entities/relationships, stores them as a graph |
| **Vector Search** | LanceDB (via Cognee) | Embedding storage for semantic search |
| **Embeddings** | FastEmbed (`BAAI/bge-small-en-v1.5`) | Local embedding model (384 dims), avoids OpenAI rate limits |
| **LLM (for Cognee)** | Groq (`llama-3.3-70b-versatile`) | Used by Cognee internally for entity extraction & answering |

---

## Data Flow — How It Works

### Ingestion Flow (Saving a Reel)

```
User pastes Reel URL in app
        │
        ▼
POST /ingest { "url": "https://instagram.com/reel/..." }
        │
        ▼  (returns immediately, processing in background)
        │
  ┌─────▼──────────────────────────────────────────┐
  │ BACKGROUND TASK — process_reel_pipeline(url)    │
  │                                                 │
  │  Step 1: yt-dlp downloads audio → temp .mp3     │
  │           Uses Chrome cookies for Instagram auth │
  │                                                 │
  │  Step 2: Groq Whisper transcribes audio → text  │
  │                                                 │
  │  Step 3: Cognee ingests transcript:             │
  │           • cognee.add() — creates dataset      │
  │           • cognee.cognify() — extracts entities,│
  │             relationships, and vector embeddings │
  │           → stored in Neo4j (graph) + LanceDB   │
  └─────────────────────────────────────────────────┘
```

### Query Flow (Asking Questions)

```
User types: "What was that recipe reel about?"
        │
        ▼
GET /chat?q=What+was+that+recipe+reel+about
        │
        ▼
cognee.search(query, SearchType.HYBRID_COMPLETION)
        │
        ▼  (combines graph traversal + vector similarity + LLM synthesis)
        │
Returns AI-generated answer grounded in stored reel transcripts
```

---

## Backend Deep Dive

**File:** [`backend/main.py`](backend/main.py) (120 lines)

### Pipeline Breakdown

#### 1. Configuration (Lines 1–38)
- Loads `.env` variables using `python-dotenv`
- Configures Cognee:
  - **LLM Provider:** Groq (via OpenAI-compatible endpoint) using `llama-3.3-70b-versatile`
  - **Embeddings:** Local FastEmbed with `BAAI/bge-small-en-v1.5` (384 dimensions)
  - **Graph DB:** Neo4j AuraDB (cloud-hosted)
  - **Vector DB:** LanceDB (local/embedded)

#### 2. Audio Download (Lines 66–76)
- Uses `yt-dlp` to extract audio from the Reel URL
- Saves to a temporary directory as `audio.mp3`
- **Important:** Uses `cookiesfrombrowser: ("chrome",)` — this means yt-dlp reads your Chrome browser's Instagram cookies to authenticate. The developer running the backend **must be logged into Instagram in Chrome**.

#### 3. Transcription (Lines 78–86)
- Sends the audio file to Groq's Whisper Large v3 model
- Returns plain text transcription

#### 4. Knowledge Ingestion (Lines 88–98)
- Prepends the source URL to the transcript
- Calls `cognee.add()` to create a dataset called `"reel_knowledge"`
- Calls `cognee.cognify()` to run Cognee's NLP pipeline:
  - Entity extraction
  - Relationship mapping
  - Vector embedding generation

### API Endpoints

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| `POST` | `/ingest` | Submit a Reel URL for background processing | `{ "url": "https://..." }` | `{ "status": "processing", "message": "..." }` |
| `GET` | `/chat` | Query the knowledge graph | `?q=your question` | `{ "query": "...", "response": "..." }` |
| `GET` | `/health` | Health check | — | `{ "status": "ok", "service": "SpillTheReel Backend" }` |

> **Note:** `/ingest` returns immediately with a 200. The actual processing happens in a FastAPI `BackgroundTask`. There is currently **no way for the frontend to know when processing completes** — no webhooks, no polling endpoint, no status tracking.

### Configuration & Environment Variables

Copy `.env.example` → `.env` and fill in:

| Variable | Source | Purpose |
|----------|--------|---------|
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | Whisper transcription + LLM (via Cognee) |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Listed in `.env.example` but **not used in `main.py`** — Cognee may use it internally as a fallback |
| `NEO4J_URI` | [neo4j.com/cloud/aura-free](https://neo4j.com/cloud/aura-free/) | Graph database connection string |
| `NEO4J_USERNAME` | Neo4j AuraDB dashboard | Usually `neo4j` |
| `NEO4J_PASSWORD` | Neo4j AuraDB dashboard | Instance password |

### External Services

| Service | Free Tier? | Notes |
|---------|-----------|-------|
| **Groq** | ✅ Yes | Generous free tier for Whisper + LLM inference |
| **Neo4j AuraDB** | ✅ Yes | Free tier available (1 instance) |
| **LanceDB** | ✅ Local | Embedded DB, no external service needed |
| **FastEmbed** | ✅ Local | Runs locally, no API calls |

---

## Frontend Deep Dive

**File:** [`frontend/App.js`](frontend/App.js) (436 lines)

Built with **React Native + Expo SDK 57**, targeting iOS, Android, and Web.

### Component Architecture

The entire frontend is a single `App` component with two main interaction modes:

```
┌─────────────────────────────────────┐
│  HEADER                             │
│  🎬 SpillTheReel / Your Reel Memory │
│  [+ Add Reel] button                │
├─────────────────────────────────────┤
│  URL INPUT PANEL (toggled)          │
│  [Paste Instagram Reel URL...] [📥] │
├─────────────────────────────────────┤
│  PROCESSING BANNER (conditional)    │
│  ⟳ Processing reel...              │
├─────────────────────────────────────┤
│                                     │
│  CHAT AREA (ScrollView)             │
│  💭 No conversations yet            │
│  🙋 User messages (purple, right)   │
│  🧠 AI responses (dark, left)       │
│  📢 System messages (center)        │
│                                     │
├─────────────────────────────────────┤
│  INPUT BAR                          │
│  [Ask your reel memory...] [→]      │
└─────────────────────────────────────┘
```

### State Management

| State Variable | Type | Purpose |
|---------------|------|---------|
| `query` | `string` | Current text in the chat input |
| `chatHistory` | `array` | All messages (`{ type: 'user'|'ai'|'system', text }`) |
| `isLoading` | `bool` | Whether a `/chat` request is in-flight |
| `ingesting` | `bool` | Whether an `/ingest` request is in-flight |
| `reelUrl` | `string` | Current text in the URL input field |
| `showUrlInput` | `bool` | Toggle for the URL input panel |

### Backend Connectivity

```javascript
const BACKEND_URL = Platform.OS === 'web'
  ? "http://localhost:8000"                              // For web dev
  : "https://unreckoned-tommy-briefly.ngrok-free.dev";   // For mobile via ngrok
```

- **Web:** Connects to `localhost:8000` directly
- **Mobile (Expo Go):** Uses an **ngrok tunnel** URL to reach the locally running backend
- ⚠️ The ngrok URL is **hardcoded** and will be **expired/invalid** for new developers. You **must** replace this with your own ngrok URL.

### UI / UX

- **Dark theme** with purple/violet accent colors (`#6d28d9`, `#a78bfa`, `#0f0f1a`)
- Chat bubbles: user messages right-aligned (purple), AI responses left-aligned (dark), system messages centered
- Fade-in animation on app mount
- Keyboard-aware input area (adjusts for iOS/Android keyboards)
- Loading states with `ActivityIndicator` for both ingestion and chat queries

---

## Getting Started — Local Setup

### Prerequisites

- **Python 3.10+** — for the backend
- **Node.js 18+** and **npm** — for the frontend
- **Google Chrome** — logged into Instagram (yt-dlp reads Chrome cookies)
- **Expo Go** app on your phone (for mobile testing) — OR just use the web browser
- Free accounts on:
  - [Groq](https://console.groq.com/) — for API key
  - [Neo4j AuraDB](https://neo4j.com/cloud/aura-free/) — for a free graph DB instance

### Backend Setup

```bash
# 1. Navigate to backend
cd backend

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Open .env and fill in your GROQ_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

# 6. Start the server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. Verify with:
```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"SpillTheReel Backend"}
```

### Frontend Setup

```bash
# 1. Navigate to frontend
cd frontend

# 2. Install dependencies
npm install

# 3. Start Expo
npx expo start
```

This will show a QR code. Options:
- **Web:** Press `w` to open in browser (connects to `localhost:8000` automatically)
- **Mobile:** Scan QR code with Expo Go app (requires ngrok tunnel — see below)

### Connecting Frontend ↔ Backend

#### Option A: Web (Easiest)
No extra setup needed. The frontend automatically uses `http://localhost:8000` on web.

#### Option B: Mobile via Ngrok
Since your phone can't access `localhost`, you need a tunnel:

```bash
# 1. Install ngrok (https://ngrok.com/download)
# 2. Start a tunnel to your backend
ngrok http 8000
```

Copy the `https://xxx.ngrok-free.dev` URL and update it in `frontend/App.js`:

```javascript
// Line 19 — replace with YOUR ngrok URL
: "https://your-ngrok-url.ngrok-free.dev";
```

Then restart Expo.

---

## Current Limitations & Known Issues

| # | Issue | Impact | Notes |
|---|-------|--------|-------|
| 1 | **Hardcoded ngrok URL** | 🔴 Mobile won't work out of the box | Each developer needs their own ngrok URL |
| 2 | **No ingestion status tracking** | 🟡 User doesn't know when a reel is done processing | `/ingest` fires and forgets; no polling/webhook |
| 3 | **Chrome cookie dependency** | 🟡 yt-dlp requires Chrome with active Instagram login | Won't work in Docker/CI or on machines without Chrome |
| 4 | **Single-file architecture** | 🟡 Not scalable | Backend is 1 file, frontend is 1 component |
| 5 | **No authentication** | 🟡 Anyone can access the API | CORS is `*`, no auth middleware |
| 6 | **No error handling for failed downloads** | 🟡 Pipeline silently fails | yt-dlp errors don't propagate to the user |
| 7 | **No database for job tracking** | 🟡 No record of what's been processed | Can't check status or list saved reels |
| 8 | **OPENAI_API_KEY in `.env.example`** | 🟢 Minor | Listed but not explicitly used in `main.py`; may be a Cognee fallback |

---

## Where To Go From Here — Contribution Ideas

### 🏗️ Architecture Improvements
- [ ] **Split backend** into proper modules: `routers/`, `services/`, `schemas/`, `core/config.py`
- [ ] **Split frontend** into components: `Header`, `ChatBubble`, `URLInput`, `ChatInput`
- [ ] Add a `docker-compose.yml` for one-command local setup
- [ ] Add `.env` validation on startup (fail fast if keys are missing)

### 🔧 Core Features
- [ ] **Ingestion status endpoint** — `GET /ingest/status/{job_id}` with progress tracking
- [ ] **Reel history** — `GET /reels` to list all ingested reels with metadata
- [ ] **Delete/forget** — ability to remove a reel from the knowledge graph
- [ ] **Batch ingest** — accept multiple URLs at once
- [ ] **Share Sheet integration** — native iOS/Android share target (requires Expo dev build, not Expo Go)

### 🔐 Security & DevOps
- [ ] Add API key authentication or JWT-based auth
- [ ] Replace hardcoded ngrok URL with env-based config
- [ ] Implement rate limiting
- [ ] Add proper logging (structured, with log levels)
- [ ] CI/CD pipeline (GitHub Actions)

### 🧪 Testing
- [ ] Backend: pytest tests for each endpoint
- [ ] Frontend: Jest + React Native Testing Library
- [ ] Integration tests for the full pipeline

### 🎨 Frontend Polish
- [ ] Navigation (React Navigation) — separate screens for Chat, History, Settings
- [ ] Persistent chat history (AsyncStorage or SQLite)
- [ ] Markdown rendering for AI responses
- [ ] Pull-to-refresh on chat
- [ ] Haptic feedback on send

---

## Commit History

| Hash | Message |
|------|---------|
| `1612ac2` | `chore: initial monorepo scaffold with fastapi and frontend placeholder` |
| `328e03f` | `feat: SpillTheReel MVP setup. Added FastAPI backend with Cognee knowledge graph and React Native Expo frontend.` |

This branch (`STRv1`) represents the **Minimum Viable Product** — a working proof-of-concept with the full pipeline from URL → audio → transcript → knowledge graph → conversational retrieval.

---

*Last updated: July 2, 2026*
