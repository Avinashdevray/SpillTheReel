"""Test pipeline for specific reels"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

# Set env vars BEFORE any Cognee imports
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
os.environ.setdefault("CACHING", "false")
os.environ.setdefault("COGNEE_SKIP_CONNECTION_TEST", "true")
os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", os.path.join(os.path.dirname(__file__), ".cognee_data"))

bluesmind_key = os.getenv("BLUESMIND", "")
if bluesmind_key:
    os.environ["OPENAI_API_KEY"] = bluesmind_key
    os.environ["OPENAI_API_BASE"] = "https://api.bluesminds.com/v1/"

# Now import cognee and configure
import cognee
cognee.config.set_llm_provider("openai")
cognee.config.set_llm_endpoint("https://api.bluesminds.com/v1/")
cognee.config.set_llm_api_key(bluesmind_key)
cognee.config.set_llm_model("openai/glm-4.6")

import asyncio
from pathlib import Path
from app.services.ingestion import download_video, transcribe_audio
from app.services.visual_audio import extract_visual_context
from app.services.brain import generate_unified_summary, save_to_memory

TEST_UID = "test_local_uid"

async def test_reel(url: str, label: str):
    print(f"\n{'='*60}")
    print(f"Testing: {label}")
    print(f"URL: {url}")
    print('='*60)

    job_id = f"test_{int(asyncio.get_event_loop().time() * 1000)}"

    print(f"\n[1/5] Downloading...")
    video_path, tmpdir, metadata = await download_video(url)
    print(f"  Video: {video_path}")
    print(f"  Metadata: {metadata}")

    try:
        print(f"\n[2/5] Transcribing...")
        transcript = await transcribe_audio(video_path)
        tl = len(transcript) if transcript else 0
        print(f"  Transcript ({tl} chars): {transcript[:200] if transcript else 'EMPTY'}...")

        print(f"\n[3/5] Extracting visual context...")
        visual_context = await extract_visual_context(video_path)
        vl = len(visual_context) if visual_context else 0
        print(f"  Visual context ({vl} chars): {str(visual_context)[:200] if visual_context else 'EMPTY'}...")

        print(f"\n[4/5] Generating summary...")
        summary = await generate_unified_summary(transcript or "", visual_context or "")
        sl = len(summary) if summary else 0
        print(f"  Summary ({sl} chars): {summary[:300] if summary else 'EMPTY'}...")

        print(f"\n[5/5] Saving to memory...")
        await save_to_memory(url, summary or "", TEST_UID)
        print(f"  Done!")

        print(f"\n  ✅ {label} complete")
    finally:
        tmpdir.cleanup()

async def main():
    reels = [
        ("https://www.instagram.com/reel/DXzhKhvzKTZ/", "Reel 1: DXzhKhvzKTZ"),
        ("https://www.instagram.com/reel/DYkUEUWEdhx/", "Reel 2: DYkUEUWEdhx"),
    ]
    for url, label in reels:
        try:
            await test_reel(url, label)
        except Exception as e:
            print(f"\n  ❌ {label} FAILED: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{'='*60}")
    print("ALL DONE")

if __name__ == "__main__":
    asyncio.run(main())
