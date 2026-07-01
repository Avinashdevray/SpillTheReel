# 🎬 SpillTheReel

**AI-Powered Audio-Visual Second Brain**

SpillTheReel is a multimodal ingestion platform that transforms video content (Reels, Shorts, TikToks, YouTube videos) into a searchable, graph-connected knowledge base powered by [Cognee](https://github.com/topoteretes/cognee).

## Architecture

```
spillthereel/
├── backend/          # FastAPI service – ingestion, transcription, OCR, graph memory
├── frontend/         # (Pending) Mobile UI – Flutter or React Native
├── docker-compose.yml
└── README.md
```

## Core Pipeline

1. **Ingest** – Accept a video URL; download via `yt-dlp`.
2. **Transcribe** – Extract speech with `faster-whisper` (WhisperX-compatible).
3. **Scene Detect** – Split into visual segments with `PySceneDetect`.
4. **OCR** – Read on-screen text using `EasyOCR`.
5. **Visual Caption** – Describe key frames with `Moondream`.
6. **Graph Memory** – Store the unified payload in Cognee's knowledge graph for semantic search.

## Quick Start

```bash
# Clone & start
docker compose up --build

# Backend is available at http://localhost:8000
# API docs at        http://localhost:8000/docs
```

## Tech Stack

| Layer       | Technology                                      |
|-------------|------------------------------------------------|
| API         | FastAPI, Pydantic v2                           |
| Download    | yt-dlp                                         |
| Transcription | faster-whisper                               |
| Scene Detection | PySceneDetect                              |
| OCR         | EasyOCR                                        |
| Vision      | Moondream                                      |
| Memory      | Cognee (knowledge graph)                       |
| Frontend    | TBD (Flutter / React Native)                   |

## License

MIT © SpillTheReel Contributors
