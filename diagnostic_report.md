# SpillTheReel Backend — Diagnostic Report
`uvicorn app.main:app --reload` run at 2026-07-02 23:54 IST

---

## ✅ What Is Running Smoothly

| Component | Status | Evidence |
|---|---|---|
| **Server startup** | ✅ Clean | `Application startup complete` — no crash |
| **`GET /health`** | ✅ 200 OK | `{"status":"ok","service":"SpillTheReel Backend","version":"0.1.0"}` |
| **OpenAPI docs** | ✅ 200 OK | `/docs` rendered correctly |
| **Input validation — /chat empty q** | ✅ 422 | Pydantic guard working |
| **Input validation — /ingest empty url** | ✅ 422 | Guard working |
| **POST /ingest (background dispatch)** | ✅ 200 | Returns `"status":"processing"` immediately |
| **Cognee auth posture** | ✅ Correct | `authentication=disabled, multi_tenant=disabled` (ENABLE_BACKEND_ACCESS_CONTROL=false working) |
| **Modular import chain** | ✅ Clean | `app.api.routes → app.services.*` all resolved |
| **CORS middleware** | ✅ Active | CORSMiddleware registered on startup |

---

## ⚠️ Issues Found (Ranked by Severity)

---

### 🔴 CRITICAL — `cookies.txt` is Missing

**Impact:** Every `/ingest` call will immediately fail with `[AuthenticationError]`.  
**Root cause:** `backend/cookies.txt` does not exist.  
**Error the pipeline will log:**
```
[AuthenticationError] cookies.txt not found at 'D:\STR_v1\backend\cookies.txt'.
```

**Fix:** Export your Instagram/YouTube cookies from your browser:
1. Install the **"Get cookies.txt LOCALLY"** Chrome extension.
2. Go to instagram.com (while logged in).
3. Click the extension → **Export** → save as `cookies.txt`.
4. Place it at `D:\STR_v1\backend\cookies.txt`.

---

### 🔴 CRITICAL — `GET /chat` Returns 500 (Cognee SQLite DB Missing)

**Impact:** Every chat query fails immediately.  
**Root cause:** Cognee's internal SQLite database hasn't been initialized yet — it only gets created after the first successful `cognee.add()` + `cognee.cognify()` run. Since no reel has ever been ingested successfully, the DB file doesn't exist.  
**Exact error:**
```
RuntimeError: [CogneeError] cognee.search for 'test'
  OperationalError: (sqlite3.OperationalError) unable to open database file
```

**Fix:** This resolves automatically once one successful `/ingest` call completes end-to-end. The DB is created at first write.

> **Short-term workaround:** Add a `cognee.prune()` + `cognee.cognify()` call in the lifespan startup to force DB initialization even with no data.

---

### 🟡 WARNING — Deprecated Gemini SDK (`google-generativeai` → `google-genai`)

**Impact:** Non-breaking today, but `google-generativeai` 0.8.6 will stop receiving updates.  
**Root cause:** The installed SDK (`google-generativeai`) is the old package. The `instructor` library (a Cognee dependency) also imports it and emits:
```
FutureWarning: All support for the `google.generativeai` package has ended.
Please switch to the `google.genai` package.
```

**Fix (when ready):** Migrate `visual_audio.py` to the new SDK:
```bash
pip uninstall google-generativeai
pip install google-genai
```
Then update `visual_audio.py`: replace `import google.generativeai as genai` with `from google import genai`.  
The Files API and GenerativeModel API have minor changes in the new SDK.

---

### 🟡 WARNING — Cognee DB Stored Inside `venv/`

**Impact:** Running `pip install --upgrade cognee` or recreating the venv **wipes the entire knowledge graph**.  
**Root cause:** Cognee defaults its database path to `venv/Lib/site-packages/cognee/.cognee_system/databases`.

**Fix:** Set `COGNEE_DATA_PATH` in `.env` to a project-level directory:
```env
COGNEE_DATA_PATH=D:\STR_v1\backend\.cognee_data
```
Add `.cognee_data/` to `.gitignore`.

---

### 🟡 WARNING — Gemini API Key Format

**Impact:** May cause `401 UNAUTHENTICATED` on first Gemini call.  
**Status:** Key has been updated to `AIzaSy...` format. Will be confirmed when the first real `/ingest` runs.

---

## 📋 Action Checklist

```
[ ] Place cookies.txt at D:\STR_v1\backend\cookies.txt
[ ] Set COGNEE_DATA_PATH in .env (move DB out of venv)
[ ] Run one real /ingest with a valid reel URL to:
      - Initialize the Cognee SQLite DB
      - Confirm Gemini key works
      - Confirm Groq Whisper works
[ ] (Later) Migrate from google-generativeai → google-genai
```
