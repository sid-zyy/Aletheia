# Aletheia: structure and model notes

Quick reference for the team. The README has full install and usage steps; `docs/ARCHITECTURE.md` has the diagram.

## Structure

| File | What it does |
|---|---|
| `app.py` | Flask API, SQLite storage, audit log, the 30 checks (`validate`), PDF report (`build_pdf`), report versions + QR verification |
| `importers.py` | CSV / Excel / SQLite / JSON in and out, using rows of `section, field, value` |
| `vision.py` | Scan reader: Gemini, Ollama, or any OpenAI-compatible service; page clean-up, part-by-part reading, saved scans |
| `static/index.html` | The whole web UI (single page) |
| `static/assistant.js` | Rule-based chat assistant: new request, record search, status, how-to answers (keyword matching, no AI model) |
| `tests/test_app.py` | 22 tests: `python -m unittest discover -s tests` |
| `sample_data/` | The A.P. Transformers sample job in every format, plus two legacy registers |

**Data:** each job stores one object per document: `request, proforma, work, losses, resistance, noload, routine, sc, temp, pressure`. It also stores `ids` (series and sample number as written on each sheet) and `other` (additional log sheets of any type, keyed `x1, x2…`).

**Workflow:** Request → Import → Review → Report → Approve.
- **Checks** run on whatever documents are present. Missing documents and empty (NA) values come out as "not evaluated", never as blockers.
- **Review:** the engineer goes through the flagged items one by one. A failed item blocks the report until it's fixed, and the report is only built once every flagged item is reviewed.
- **Editing data** sends the job back to Import, so the checks and report are always redone.

**Files kept beside the database:**
- `aletheia.db`: the jobs.
- `ai_cache.db`: saved scans. It survives deleting the jobs database, and git ignores both.

## Using the scanner (AI reading)

Settings are environment variables, set before `python app.py`. They're saved as user variables on Kenzyy's PC.

| Variable | Value used | Purpose |
|---|---|---|
| `AI_BASE_URL` | `http://localhost:11434/v1` | Ollama on this PC (port 11434 means Ollama's own API is used) |
| `AI_MODEL` | `qwen2.5vl:3b` | Model name; `qwen2.5vl:7b` for better tables |
| `AI_TIMEOUT` | `900` | Seconds per request |
| `AI_NUM_CTX` | 8192 (default) | Model working memory |
| `AI_MAX_TOKENS` | 3000 (default) | Cap on answer length |
| `AI_IMAGE_PX` | 1024 (default) | Page image size (Ollama resizes anyway) |
| `AI_AUTOROTATE` | 1 (default) | Turn sideways pages upright |
| `GEMINI_API_KEY` | (unset) | Use Gemini instead; free tier often answers "busy" (503) |

**How a scan is read:**
1. **Page cleanup:** each page is turned upright if needed and converted to high-contrast grayscale.
2. **Empty layout, never real values:** the model gets an empty layout (field names + `<number>`/`<text>`) plus a description of each field in the form's own words. An early version sent the sample's real values and the model just copied them; those "100%" results were fake.
3. **Enforced answer shape:** Ollama forces the answer into that exact JSON shape, which stops the model looping.
4. **Big sheets in parts:** header fields first, then each large table, so the form fills in part by part.
5. **Tick boxes:** record only the ticked or circled option; repeated labels on "Other" sheets are removed and flagged.
6. **Saved scans:** results are stored in `ai_cache.db` by scan fingerprint + part + model, so a second scan of the same sheet is instant and works offline.

**Measured on this laptop** (i9-13900H, CPU only, `qwen2.5vl:3b`):
- **Speed:** about 45 s to process each page image plus about 10–16 tokens/s for the answer, so short sheets take 20–45 s.
- **Short forms, read whole:** work instruction ~4 of 8 right (names and years slip); request form 11/15; proforma 11/24.
- **Big tables, read whole (before parts and the enforced shape):** losses and resistance looped for 12–13 min and failed.
- **Short-circuit sheet in parts:** 129 s, 53/111 right. Values slid one column because the sheet's "Voltage applied U/V/W" columns aren't in the layout; the scanner is now told to skip them (not yet re-measured).
- **Handwritten crops (21 fields):** Qwen 3B 11/21 exact, all 9 numbers right, 54 s each. TrOCR base 3/21 at 2.8 s, but it **drops decimal points** (16.80 → "1680"), so it's not used. TrOCR small is unusable.

**Gotchas:**
- **One reading at a time:** Ollama runs one reading at a time; a second request waits in line.
- **First scan after idle:** Ollama unloads the model after 5 idle minutes. Set `OLLAMA_KEEP_ALIVE=-1` to keep it loaded.
- **Restart after Python changes:** restart the app; the browser only needs a refresh for UI changes.
- **Sideways detection:** thresholds are tuned on the 9 sample scans; check the notes ("page N was turned upright").

## Recommendations

- **Speed:** run Ollama on an NVIDIA GPU (RTX 3060 12 GB → `qwen2.5vl:7b`, a few seconds per page). Check with `ollama ps` that it says "100% GPU".
- **Accuracy without a GPU:** hosted Qwen2.5-VL-72B via OpenRouter (`AI_BASE_URL=https://openrouter.ai/api/v1`, `AI_API_KEY`).
- **Demo day:** scan every sheet once beforehand, so the saved scans load instantly on stage. Keep the CSV import as the no-AI fallback (`test-files/`).
- **Fine-tuning later:** every engineer-corrected scan is a labelled example. Fine-tune once a few hundred sheets are collected; it isn't practical with one job's 15 pages.
