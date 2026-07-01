import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Disable backend access control to avoid multi-user handler conflicts
os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"

import asyncio
import tempfile
import yt_dlp
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import cognee
from cognee.modules.search.types.SearchType import SearchType

# Configure Cognee programmatically using Groq + Fastembed + Neo4j
cognee.config.set_llm_provider("openai")
cognee.config.set_llm_endpoint("https://api.groq.com/openai/v1")
cognee.config.set_llm_api_key(os.getenv("GROQ_API_KEY"))
cognee.config.set_llm_model("openai/llama-3.3-70b-versatile")

# Use local fastembed for embeddings to avoid OpenAI rate limits
cognee.config.set_embedding_provider("fastembed")
cognee.config.set_embedding_model("BAAI/bge-small-en-v1.5")
cognee.config.set_embedding_dimensions(384)

# Configure Neo4j Graph DB connection
cognee.config.set_graph_database_provider("neo4j")
cognee.config.set_graph_db_config({
    "graph_database_url": os.getenv("NEO4J_URI"),
    "graph_database_username": os.getenv("NEO4J_USERNAME"),
    "graph_database_password": os.getenv("NEO4J_PASSWORD")
})
cognee.config.set_vector_db_provider("lancedb")


app = FastAPI(title="SpillTheReel API", version="0.1.0")

# Allow requests from the Expo mobile app (any origin for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Groq client for Whisper transcription
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class ReelRequest(BaseModel):
    url: str


async def process_reel_pipeline(url: str):
    """
    Full pipeline: download audio → transcribe → ingest into Cognee knowledge graph.
    This runs as a background task so the mobile app doesn't hang.
    """
    # STEP 1: Download Audio using yt-dlp
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.mp3")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": audio_path,
            "quiet": True,
            "cookiesfrombrowser": ("chrome",),  # Uses your Chrome Instagram login
        }
        print(f"[1/3] Downloading audio from: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # STEP 2: Transcribe with Groq (Whisper)
        print("[2/3] Transcribing audio with Groq Whisper...")
        with open(audio_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(audio_path, file.read()),
                model="whisper-large-v3",
                response_format="text",
            )
        print(f"[2/3] Transcript: {transcription[:200]}...")

    # STEP 3: Ingest into Cognee Memory Graph
    # Prefix the text with the URL so we have a reference
    document_text = f"Source URL: {url}\n\nTranscript: {transcription}"

    print("[3/3] Ingesting into Cognee knowledge graph...")
    # cognee.add creates the dataset
    await cognee.add(document_text, "reel_knowledge")

    # cognee.cognify extracts entities, relationships, and vectors
    await cognee.cognify("reel_knowledge")
    print(f"✅ Successfully memorized Reel: {url}")


@app.post("/ingest")
async def ingest_reel(req: ReelRequest, background_tasks: BackgroundTasks):
    """Accept a reel URL and process it in the background."""
    background_tasks.add_task(process_reel_pipeline, req.url)
    return {"status": "processing", "message": "Reel is being added to memory."}


@app.get("/chat")
async def query_memory(q: str):
    """Query the Cognee knowledge graph with natural language."""
    # query_type can be SearchType.HYBRID_COMPLETION, SearchType.GRAPH_COMPLETION, etc.
    results = await cognee.search(q, query_type=SearchType.HYBRID_COMPLETION)
    return {"query": q, "response": results}


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "SpillTheReel Backend"}
