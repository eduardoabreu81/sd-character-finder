<div align="center">

[![SD WebUI](https://img.shields.io/badge/SD_WebUI-A1111%20%7C%20Forge-blue)](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
[![Forge Neo](https://img.shields.io/badge/Forge-Neo-blue)](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)
[![Gradio](https://img.shields.io/badge/Gradio-4.x-orange)](https://gradio.app/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

# 🎭 SD Character Finder

<div align="center">

> **Extension for Stable Diffusion WebUI (A1111 / Forge / Forge Neo)**

</div>

Browse **20,000+ Danbooru characters** directly inside your SD WebUI — search by name, tag or series, preview the character card with thumbnail, and send prompt tags straight to txt2img with one click.

---

## 📋 Table of Contents

- [What's New](#-whats-new)
- [Changelog](#-changelog)
- [Roadmap](#️-roadmap)
- [Features](#-features)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Character Database](#-character-database)
- [Standalone Mode](#-standalone-development-mode)
- [Credits](#-credits)

---

## 🆕 What's New

### v1.2.0 — Configuration & Pagination *(current)*

- **Dead Code Removal** — removed legacy modules related to wildcard pack creation and prompt generation to focus 100% on the single-tab character browsing experience.
- **WebUI Settings Integration** — added native `shared.opts` integration for `sdcf_search_limit`, `sdcf_live_n_posts`, API keys, etc. You can now configure limits and credentials inside your SD WebUI Settings tab.
- **Robust Error Logging** — implemented `logging` wrappers across DB and API touchpoints for simpler remote diagnostics.
- **Safe DB Teardown** — added `atexit` hooks to manage SQLite connections correctly to prevent lockouts.
- **Pagination** — results are now paginated via simple `Prev`/`Next` buttons, preventing Gradio dataframe crashes from large queries (e.g. searching "All" with no limits).
- **Tag Cache & Rate Limits** — Live API calls now cache locally for `sdcf_live_cache_ttl` seconds, adhering cleanly to `sdcf_scraper_rate_limit`.
- **Loading Spinners & Feedback** — The Live tag fetching now explicitly displays loading text during the IO request to avoid frustrating silent waits.
- **Enhanced Normalization** — Live tags with underscores are perfectly recognized alongside user spaces for accurate deduplications on send.
- **Background Auto-Scraping** — If the database starts completely empty (e.g. when downloaded without `characters.db`), the extension automatically spins up a background thread to safely scrape all 20,000 Danbooru tags directly from the web source, skipping the need for manual python script triggers!

### v1.1.0 — UX Improvements

- **Clear button** — reset search query, filters, results table, and selected card with one click
- **Add to txt2img** — new button appends tags to existing prompt (deduplication by lowercase)
- **Live Danbooru enrichment** — optional accordion fetches extra tags via Danbooru API, grouped by category (character/general/copyright), with checkboxes and NovelAI-like ordering
- **DB tags are always used as base** — fixed bug where canonical_tag could override full tags from the database

### v1.0.1 — WebUI Integration Fixes *(patch)*
- **Tab now appears correctly** in all SD WebUI forks — fixed `on_ui_tabs` callback returning a bare `Blocks` object instead of the required tuple
- **Send to Generate** now injects tags directly into `#txt2img_prompt` via JavaScript — works in any WebUI environment without server-side dependencies
- **Copy Tags** now uses `navigator.clipboard` with `execCommand` fallback for HTTP (non-secure) contexts — works on local network, LAN, and tunnels

---

## 📖 Changelog

### v1.0.1 — WebUI Integration Fixes *(patch)*
- Fixed `TypeError: 'Blocks' object is not iterable` on extension load (`on_ui_tabs` must return a list of tuples)
- Fixed tab rendering empty — removed nested `gr.Tab` wrapper inside `gr.Blocks` returned to `on_ui_tabs`
- Renamed tab from `🎭 Characters` to `Danbooru Characters`
- Send to Generate: replaced broken `modules.generation_parameters_copypaste` call with JS injection into `#txt2img_prompt textarea`
- Copy Tags: replaced server-side `tkinter` clipboard (fails on Linux headless) with `navigator.clipboard.writeText()` + `execCommand('copy')` fallback for HTTP

### v1.0.0 — Initial Release *(minor)*
- 20,016 Danbooru characters indexed in SQLite (`data/characters.db`, ~7 MB)
- Search by name or tag, filter by series
- Character card with thumbnail, name, series, and prompt tags
- Send to txt2img and Copy Tags buttons
- Compatible with A1111, Forge, and Forge Classic (neo)

---

## 🗺️ Roadmap

### v1.0.0 — Initial Release *(complete)* ✅

### v1.0.1 — WebUI Integration Fixes *(complete)* ✅
- Fixed tab registration and rendering
- JS-based Send to Generate and Copy Tags

### v1.1.0 — UX Improvements *(complete)* ✅
- Clear button to reset search and results
- Add to txt2img (append with deduplication)
- Live Danbooru tag enrichment with category checkboxes
- NovelAI-like tag ordering for enriched prompts

### v1.2.0 — Foundation & Configuration *(complete)* ✅
- Single-tab architecture explicitly enforced.
- Configurable variables in WebUI `shared.opts`.
- Comprehensive module cleanup & debug logging readiness.

---

## 🎯 Features

### 🔍 Browse & Search

- Search 20,016 characters by **name or tag** (e.g. `miku`, `saber`, `blue hair`)
- Filter by **series** (Pokémon, Touhou, Fate, Hololive, Azur Lane, and more)
- Results table with name, series, and rank
- Click any row to load the full character card

### 🃏 Character Card

- **Thumbnail preview** — lazy-loaded from Danbooru source
- Character name and series fields
- **Editable prompt tags** — review and tweak before sending

### ➡️ Send to txt2img

- **Send to Generate** — replaces prompt with selected tags
- **Add to txt2img** — appends tags to existing prompt (deduplication by lowercase)
- Both implemented via JavaScript DOM injection — works in any WebUI fork, any hosting environment

### 📋 Copy Tags

- Copies tags to clipboard via `navigator.clipboard` (HTTPS/localhost)
- Falls back to `execCommand('copy')` for plain HTTP (local network, LAN setups)

### 🔄 Clear Search

- One-click reset of search query, filters, results table, and selected card

### 🌐 Live Danbooru Enrichment (optional)

- Fetch extra tags directly from Danbooru for the selected character
- Tags grouped by category: character, general, copyright
- Checkbox selection with automatic prompt assembly
- NovelAI-like ordering: count tags (1girl/1boy) → character → series → others

### 🖥️ Standalone Mode

- Run the UI locally without SD WebUI for development and testing

---

## 📦 Installation

### Inside SD WebUI (recommended)

1. Open **Extensions → Install from URL**
2. Paste: `https://github.com/eduardoabreu81/sd-character-finder`
3. Click **Install**, then **Apply and restart UI**

### Manual

```bash
cd <webui_root>/extensions
git clone https://github.com/eduardoabreu81/sd-character-finder
# Restart WebUI
```

> ✅ Compatible with **AUTOMATIC1111**, **Forge**, and **Forge Classic (neo)**

---

## 🚀 Quick Start

1. Open the **Danbooru Characters** tab
2. Type a character name or tag — e.g. `miku`, `saber`, `blue hair`
3. Optionally filter by series
4. Click **🔍 Search**
5. Click a row in the results table to load the character card
6. Click **➡️ Send to Generate** to populate txt2img

---

## 🗃️ Character Database

The extension ships with a pre-built SQLite database of **20,016 characters** (`data/characters.db`, ~7 MB, included in the repo).

### Top series

| Series | Characters |
|---|---|
| Pokémon | 1,315 |
| Kantai Collection | 574 |
| Azur Lane | 474 |
| Fate/series | 437 |
| Hololive | 411 |
| Touhou | 400+ |
| Girls' Frontline | 350+ |

### Rebuild from scratch

```bash
python scripts/scrape_characters.py
# ~14 min, 834 pages, ~20k characters
```

Data sourced from [downloadmost.com/NoobAI-XL/danbooru-character](https://www.downloadmost.com/NoobAI-XL/danbooru-character/) (`robots.txt: Allow: /`).

---

## 🖥️ Standalone Development Mode

Run without an SD WebUI installation:

```bash
pip install gradio beautifulsoup4 requests
python -m wildcard_creator.ui
# → http://127.0.0.1:7861
```

Custom port:

```bash
python -m wildcard_creator.ui 7862
```

---

## 📄 Credits

- **[Danbooru](https://danbooru.donmai.us/)** — character tag database
- **[NoobAI-XL Danbooru Character List](https://www.downloadmost.com/NoobAI-XL/danbooru-character/)** — source for the character scraper
- **[Forge Neo](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)** by Haoming02

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Made with ❤️ for the Stable Diffusion community

**[Report Bug](https://github.com/eduardoabreu81/sd-character-finder/issues)** • **[Request Feature](https://github.com/eduardoabreu81/sd-character-finder/issues)** • **[Discussions](https://github.com/eduardoabreu81/sd-character-finder/discussions)**

</div>
