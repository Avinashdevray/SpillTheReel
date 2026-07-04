# SpillTheReel — Context (improved branch)

## Product
SpillTheReel is an AI-powered second brain for Instagram Reels. You share a Reel URL, the app downloads it, extracts audio (ffmpeg), transcribes via Groq Whisper, extracts visual context (Bluesmind / Gemini), merges everything into a unified summary (Groq Llama 3.3), and stores it in a LanceDB vector store and Neo4j graph DB via Cognee. You can then ask natural-language questions about what you've watched, and it returns conversational AI answers using your saved reels.

---

## Current Architecture

```
POST /ingest ──→ asyncio.create_task(_run_ingest_pipeline)
                    ├─ 1. download_video()          yt-dlp + cookies.txt
                    ├─ 2. transcribe_audio()         ffmpeg → MP3 → Groq Whisper
                    ├─ 3. extract_visual_context()   Bluesmind (gpt-4o) / Gemini 2.0 Flash
                    ├─ 4. generate_unified_summary() Groq Llama 3.3
                    ├─ 5. save_to_memory()           Cognee add() + Neo4j User-isolated Reel nodes
                    └─ 🔄 tmpdir.cleanup()

GET /chat?q=... ──→ query_memory() ──→ Keyword overlap scoring → generate_chat_answer() (Groq)
GET /share-target ─→ Web Share Target route for PWA (receives URL → queues /ingest)
```

## End Goal

A complete web app deployed at a public URL with:
- **Firebase Auth** — Google sign-in, email/password authentication (✅ Done)
- **Installable PWA** — works in Chrome as a standalone app (manifest + service worker) (✅ Done)
- **Instagram share sheet** — share a Reel directly from Instagram → opens the app → auto-ingests (✅ Done via Web Share Target)
- **Real-time progress** — WebSocket/SSE for pipeline status
- **Query history** — persistent chat per user (✅ Done via Neo4j user isolation)
- **Polished dark-mode UI** — loading states, error feedback (✅ Done)

---

## Setup Instructions

### 1. Backend — Python virtual environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Backend — Environment variables

Copy `.env.example` to `.env` and fill in credentials:

Required credentials:
| Variable | Source | Purpose |
|---|---|---|
| `BLUESMIND` | _Optional_ | OpenAI-compatible key for Cognee entity extraction (gpt-4o) and primary visual extraction |
| `OPENAI_API_KEY` | _Optional_ | Not needed if using Bluesmind |
| `GROQ_API_KEY` | https://console.groq.com/keys | Whisper transcription + Llama 3.3 summary + Chat Answers |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | Visual context extraction (fallback if Bluesmind not set) |
| `NEO4J_URI` | https://neo4j.com/cloud/aura-free/ | Graph DB connection URI |
| `NEO4J_USERNAME` | Neo4j AuraDB | Graph DB user |
| `NEO4J_PASSWORD` | Neo4j AuraDB | Graph DB password |

### 3. Backend — cookies.txt

yt-dlp requires Instagram authentication cookies. Export your browser cookies in **Netscape format** and save as `backend/cookies.txt`.

### 4. Backend — Run server

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. Frontend — Install & Run

```bash
cd frontend
npm install
npx expo export -p web
firebase deploy --only hosting
```

---

## What's Done (Proven & Live)

- **Firebase Authentication**: Full integration with Email/Password and Google Sign-In. Users are strictly isolated.
- **Neo4j User Isolation**: Data is saved as `(User {firebase_uid}) -[:SAVED]-> (Reel)`. Users only query their own reels.
- **Smart Chat Answers**: Instead of a generic list, the backend passes the top matching reel and the user's question to Groq (Llama 3.3) to generate a conversational, direct answer.
- **Improved Search**: Replaced exact Cypher `CONTAINS` string matching with an intelligent Python-based keyword overlap scoring system (stripping stop words).
- **Bluesmind Priority**: Visual context extraction now prioritizes the `BLUESMIND` (GPT-4o) endpoint to bypass Gemini's strict rate limits.
- **Frontend Feedback**: Fixed the "processed and indexed" premature message. The frontend now accurately reflects the actual processing message from the backend.
- **Web Share Target (PWA)**: Added manifest and routing so Android/iOS users can share a Reel from Instagram directly to the SpillTheReel PWA.

---

## Pending & Remaining Things

- **WebSocket/SSE**: Replace polling/static messages with real-time progress updates during the ingestion pipeline.
- **Status Endpoint**: Add a dedicated endpoint to check the processing state of a specific reel (useful if the user refreshes the page while a reel is being ingested).
- **Frontend Polish**: Add animations for Reel cards entering the chat. 
- **Production Deploy**: Package the backend in a Docker container and set up secure CORS policies.

## Key Files

| File | Purpose |
|---|---|
| `backend/app/main.py` | FastAPI entry, Cognee config |
| `backend/app/api/routes.py` | POST /ingest, GET /chat, GET /share-target |
| `backend/app/services/repository.py` | Neo4j operations, query search logic, user isolation |
| `backend/app/services/visual_audio.py` | Bluesmind/Gemini visual extraction |
| `backend/app/services/brain.py` | Groq summary, Cognee storage, conversational chat answers |
| `frontend/App.js` | Main React Native Web frontend |
| `frontend/firebaseConfig.js` | Firebase initialization |
| `context.md` | This file |
