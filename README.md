# � SD Character Finder

An SD WebUI extension (AUTOMATIC1111 / Forge) for browsing **20,000+ Danbooru characters** and sending their prompt tags directly to txt2img.

---

## Features

| Feature | Description |
|---|---|
| **Character Browser** | Search 20k+ characters by name or tag across all major anime series |
| **Series Filter** | Filter results by franchise (Pokémon, Touhou, Fate, Hololive, and more) |
| **Tag Preview** | View the character's prompt tags and thumbnail before sending |
| **Send to txt2img** | One-click to populate the positive prompt field in SD WebUI |
| **Copy Tags** | Copy tags to clipboard for use anywhere |
| **Standalone mode** | Run the UI locally without SD WebUI (for development) |

---

## Installation

### Inside SD WebUI
1. Open **Extensions → Install from URL**
2. Paste: `https://github.com/YOUR_USERNAME/sd-character-finder`
3. Click **Install**, then **Apply and restart UI**

### Manual
```bash
cd <webui_root>/extensions
git clone https://github.com/YOUR_USERNAME/sd-character-finder
# Restart WebUI
```

---

## Quick Start

1. Open the **🎭 Characters** tab
2. Type a character name or tag (e.g. `miku`, `saber`, `blue hair`)
3. Optionally filter by series
4. Click **🔍 Search**
5. Click a row in the results table to load the character card
6. Click **➡️ Send to Generate** to populate txt2img

---

## Character Database

The extension ships with a pre-built SQLite database of **20,016 characters** scraped from Danbooru tag listings (`data/characters.db`, ~7 MB).

Top series included:

| Series | Characters |
|---|---|
| Pokémon | 1,315 |
| Kantai Collection | 574 |
| Azur Lane | 474 |
| Fate/series | 437 |
| Hololive | 411 |

To rebuild the database from scratch:

```bash
python scripts/scrape_characters.py
# ~14 min, 834 pages
```

---

## Standalone Development Mode

Run the UI without an SD WebUI installation:

```bash
pip install gradio beautifulsoup4 requests
python -m wildcard_creator.ui
# → opens at http://localhost:7861
```

Or with a custom port:

```bash
python -m wildcard_creator.ui 7862
```

---

## Compatibility

| SD WebUI | Compatibility |
|---|---|
| AUTOMATIC1111 | ✅ |
| Forge | ✅ |

---

## License

MIT
