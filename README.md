# VibeTranslate

<p align="center">
  <img src="vibetranslate_thumbnail.png" alt="VibeTranslate Banner" width="800">
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="https://creativecommons.org/licenses/by/4.0/"><img src="https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg" alt="License: CC BY 4.0"></a>
  <a href="https://ai.google.dev/"><img src="https://img.shields.io/badge/Gemini-2.5%20Flash-orange.svg" alt="Gemini 2.5 Flash"></a>
</p>

**VibeTranslate** is a context-aware, multi-agent translation pipeline built natively with the Google GenAI SDK (`gemini-2.5-flash`) to translate Chinese web novels into high-quality, formatted English Markdown.

Designed as a Capstone Project for the Google/Kaggle 5-Day AI Agents Intensive Course, it implements custom batch-processing, session pacing, glossary persistence, and a stateful context-awareness system.

---

## Key Features

1. **Stateful Context-Awareness (`story_context.json`):** Resolves the "chapter isolation" problem (such as character gender flipping, abrupt tone shifts, and lost narrative threads) by tracking:
   - A rolling high-level summary of the novel.
   - Chapter-by-chapter summaries.
   - Narrative details at the end of the previous chapter (active characters in scene, location, active cliffhangers).
   - Preceding chapter ending paragraphs for styling baseline and narrative continuity.
2. **Hybrid Programmatic + Agentic QC (`editor.py`):** Automatically validates translated text against strict styling rules (max 3 sentences per paragraph, blank lines between paragraphs, dialogue formatting, Chinese character leakage) using fast programmatic regex. If a rule is violated, it calls a GenAI correction agent to perform a targeted rewrite.
3. **Local-First Ingestion:** Defaults to reading local raw text files (`temp/ch{N}_raw.txt`) to ensure grading and demonstrations execute reliably without triggering Cloudflare blocks or captcha challenges on live novel sites.
4. **Glossary Management (`glossary.json`):** Tracks characters, locations, items, techniques, and organizations. Supports manual character name overrides and automatically adds new terms discovered by the translation agent.

---

## Directory Structure

```
vibe_translate_project/
├── config.json                     # Default paths, model configuration, and timing limits
├── requirements.txt                # Python dependencies
├── generate_mock_chapters.py       # Helper script to generate mock chapters offline
├── main.py                         # Main orchestrator script
├── README.md                       # Setup and usage instructions
└── src/
    ├── __init__.py
    ├── glossary.py                 # Glossary parsing, loading, and markdown exporting
    ├── context_manager.py          # State tracking registry and summaries updater
    ├── extractor.py                # Local text reader and fallback web scraper
    ├── translator.py               # GenAI Translation agent
    └── editor.py                   # Programmatic checks and correction agent
```

---

## Setup Instructions

### 1. Install Dependencies
Ensure you have Python 3.10+ installed. In your terminal, run:
```bash
pip install -r requirements.txt
```

### 2. Configure Gemini API Key
Export your Gemini API Key in your terminal session before running the pipeline:

* **Windows PowerShell:**
  ```powershell
  $env:GEMINI_API_KEY="your_api_key_here"
  ```
* **Windows CMD:**
  ```cmd
  set GEMINI_API_KEY=your_api_key_here
  ```
* **macOS/Linux:**
  ```bash
  export GEMINI_API_KEY="your_api_key_here"
  ```

---

## Usage

### Step 1: Generate Mock Chapters (For Testing/Grading)
To generate mock Chinese chapters locally without web scraping:
```bash
python generate_mock_chapters.py
```
This will populate three mock chapter files in the `temp/` directory:
- `temp/ch1_raw.txt`
- `temp/ch2_raw.txt`
- `temp/ch3_raw.txt`

### Step 2: Run the Translation Pipeline
Execute the main orchestrator script:
```bash
python main.py --novel-title "Universal Fanfiction Crossover" --start 1 --end 3
```

During execution, the script will:
1. Ingest the mock Chinese chapters from `temp/`.
2. Translate each chapter sequentially using the rolling glossary and narrative context.
3. Automatically update `output/story_context.json` and `output/glossary.json` with new plot points and terms.
4. Run programmatic checks and execute any editor corrections.
5. Wait **5 seconds** between sessions to pace requests.
6. Merge all chapters into `output/Universal_Fanfiction_Crossover_ch1-3.md` and clean up temporary chapter files.

### Step 3: Run with Custom Character Name Overrides
To force specific translation mappings (e.g. mapping `叶凡` to `Ye Fan` or custom names), use the `--overrides` flag:
```bash
python main.py --novel-title "Universal Fanfiction Crossover" --start 1 --end 3 --overrides "叶凡:Ye Fan,宇智波止水:Shisui Uchiha"
```
