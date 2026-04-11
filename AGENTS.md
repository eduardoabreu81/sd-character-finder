# AGENTS.md — SD Character Finder

> Guide for AI coding agents working on this project.
> This is a **Stable Diffusion WebUI extension** for browsing Danbooru/e621 characters.

---

## Project Overview

**SD Character Finder** is a browser extension for [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui) and [Forge](https://github.com/Haoming02/sd-webui-forge-classic) that provides:

- Browse **23,000+ characters** (Danbooru + e621) offline via SQLite
- Search by name, tag, or series with multi-term AND logic
- Visual gallery with thumbnail grid
- One-click prompt generation (Send to txt2img / Add to txt2img)
- Live Danbooru API integration for extra character tags
- Favorites and search history persistence
- Wildcard export for sd-dynamic-prompts

**Current Version:** v0.5.2

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| UI Framework | [Gradio](https://gradio.app/) 3.x/4.x (compatible with both) |
| Database | SQLite3 (stdlib) |
| HTTP/Scraping | `requests`, `beautifulsoup4` |
| CSS | Custom WebKit scrollbars, AG Grid overrides |

### Dependencies

Core dependencies (managed by WebUI's `launch`):
- `gradio` (provided by WebUI)
- `requests`
- `beautifulsoup4`
- `pyyaml`

No `requirements.txt` or `pyproject.toml` — dependencies are checked in `install.py`.

---

## Project Structure

```
sd-character-finder/
├── scripts/
│   └── wildcard_creator.py      # WebUI entry point (tab registration)
├── wildcard_creator/            # Main package (legacy name, don't rename)
│   ├── __init__.py
│   ├── ui.py                    # Gradio UI (1,500+ lines)
│   ├── character_db.py          # SQLite database interface
│   ├── danbooru.py              # Danbooru API + CSV tag database
│   ├── favorites.py             # Favorites JSON persistence
│   ├── search_history.py        # Search history JSON persistence
│   └── utils/
│       └── strings.py           # Normalization utilities
├── scripts/                     # Maintenance scripts
│   ├── scrape_characters.py     # Scrape Danbooru characters
│   ├── scrape_e621.py           # Scrape e621 characters
│   ├── resolve_danbooru_tags.py # Match DB names to Danbooru tags
│   ├── fix_truncated_tags.py    # Fix incomplete tag strings
│   └── clean_series_metadata.py # Normalize series names
├── data/                        # Runtime data (git-tracked)
│   ├── characters.db            # SQLite database (~23k characters)
│   ├── danbooru_tags.csv        # Curated tag dictionary
│   ├── favorites.json           # User favorites (runtime)
│   ├── search_history.json      # Recent searches (runtime)
│   ├── recent_viewed.json       # Recently viewed (runtime)
│   └── covers/                  # Cached thumbnails (gitignored)
├── wildcards/                   # Output folder for TXT wildcards
├── style.css                    # Custom CSS (Gradio 4 patches)
├── install.py                   # Extension install hook
└── test_df.py                   # Dev utility for testing Gradio
```

---

## Architecture

### Two Entry Points

1. **WebUI Mode** (production):
   ```python
   # scripts/wildcard_creator.py
   from wildcard_creator.ui import build_ui
   blocks = build_ui()  # Returns gr.Blocks
   ```

2. **Standalone Mode** (development):
   ```bash
   python -m wildcard_creator.ui 7861
   # Runs on http://127.0.0.1:7861
   ```

### Database Schema

```sql
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,           -- Display name (e.g., "Hatsune Miku")
    series TEXT,                  -- Franchise/series name
    tags TEXT NOT NULL,           -- Prompt-ready tags
    image_url TEXT,               -- Thumbnail CDN URL
    rank INTEGER,                 -- Popularity rank (1-20k Danbooru, 20k+ e621)
    danbooru_tag TEXT,            -- Canonical Danbooru tag (with spaces)
    source TEXT DEFAULT 'danbooru'  -- 'danbooru' or 'e621'
);
```

### Key Data Flows

1. **Search Flow:**
   - User input → `character_db.search()` → SQLite query → DataFrame/Gallery render
   - Multi-term query uses `AND` logic (all terms must match)

2. **Character Selection:**
   - Row click in DataFrame OR card click in Gallery
   - Hidden `Textbox` element receives index via JavaScript
   - `_select_by_index()` loads character data → updates preview panel

3. **Live Tags Fetch:**
   - `danbooru_tag` → Danbooru API `/posts.json` → tag frequency analysis
   - Categories: Character(4), Copyright(3), General(0), Artist(1), Meta(5)
   - NovelAI-style ordering applied before prompt insertion

4. **Favorites System:**
   - `favorites.json` stores character IDs
   - Toggle via "Favorite" button → updates preview badge + favorites tab

---

## Development

### Running Locally (Standalone)

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Run standalone UI
python -m wildcard_creator.ui 7861
# Open http://127.0.0.1:7861
```

### Rebuilding the Database

```bash
# 1. Scrape Danbooru characters (~20k, ~14 min)
python scripts/scrape_characters.py --resume

# 2. Scrape e621 characters (~3k, ~2 min)
python scripts/scrape_e621.py --resume

# 3. Resolve Danbooru tags (requires API key)
python scripts/resolve_danbooru_tags.py --login USER --api-key KEY --resume

# 4. Fix truncated tags (requires CSV dump)
python scripts/fix_truncated_tags.py --csv data/danbooru_tags.csv

# 5. Clean series metadata
python scripts/clean_series_metadata.py
```

### Database Migrations

The codebase uses runtime migration in `character_db._migrate()`:

```python
# Adding new columns safely
for ddl in [
    "ALTER TABLE characters ADD COLUMN danbooru_tag TEXT",
    "ALTER TABLE characters ADD COLUMN source TEXT DEFAULT 'danbooru'",
]:
    try:
        self._conn.execute(ddl)
    except sqlite3.OperationalError:
        pass  # column already exists
```

---

## Testing

### Manual Testing Checklist

When modifying UI code, verify in **both** modes:

- [ ] Search returns results (List + Gallery views)
- [ ] Character selection updates preview panel
- [ ] Gallery card click works
- [ ] Pagination (Prev/Next, page jump)
- [ ] Favorites toggle and persistence
- [ ] "Send to txt2img" / "Add to txt2img" (WebUI only)
- [ ] Live tags fetch (requires API key)
- [ ] Export TXT wildcard
- [ ] Recent searches dropdown
- [ ] Recently viewed persistence

### Test Script

```bash
# Quick Gradio DataFrame test
python test_df.py
```

---

## Code Style Guidelines

### Python

- **Type hints:** Use `from __future__ import annotations` and modern syntax
- **Quotes:** Double quotes for strings
- **Line length:** ~100 characters (soft limit)
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes
- **Docstrings:** Google-style or concise single-line for simple functions

### Gradio Compatibility

**Critical:** Support both Gradio 3 and 4:

```python
_GR_VERSION = getattr(gr, "__version__", "3.0.0")

def get_js_kw(js_script: str) -> dict:
    """Helper to maintain compat with Gradio 3 (_js) and Gradio 4 (js)."""
    return {"js": js_script} if int(str(_GR_VERSION).split(".")[0]) >= 4 else {"_js": js_script}

# Usage
btn.click(fn=handler, inputs=[...], outputs=[...], **get_js_kw("alert('ok')"))
```

### CSS Conventions

- All selectors prefixed with `#sdcf_main_blocks` or `.sdcf-*` for isolation
- Gradio 4 DataFrame requires aggressive reset CSS (see `style.css` lines 283-403)
- Custom scrollbars use WebUI CSS variables for theme sync

### JavaScript in Python

Keep inline JS in `**get_js_kw()` calls readable with multiline strings:

```python
**get_js_kw("""
    const switchToTab = (target) => { ... };
    const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
    ...
""")
```

---

## Configuration

Settings are registered in `scripts/wildcard_creator.py` via WebUI's `shared.opts`:

| Setting Key | Default | Description |
|-------------|---------|-------------|
| `sdcf_danbooru_login` | "" | Danbooru API login |
| `sdcf_danbooru_api_key` | "" | Danbooru API key (password field) |
| `sdcf_search_limit` | 30 | Results per page (5-30) |
| `sdcf_gallery_thumb_size` | 160 | Thumbnail size in px |
| `sdcf_gallery_columns` | 5 | Cards per row |
| `sdcf_add_deduplicate` | True | Deduplicate on "Add to txt2img" |
| `sdcf_live_n_posts` | 120 | Posts to sample for live tags |
| `sdcf_live_top_n` | 40 | Tags to return from live fetch |
| `sdcf_live_min_freq` | 0.08 | Minimum tag frequency threshold |
| `sdcf_scraper_rate_limit` | 1.0 | Seconds between API requests |
| `sdcf_live_cache_ttl` | 1800 | Cache TTL for live tags (seconds) |

Access in code:
```python
try:
    from modules import shared
    limit = getattr(shared.opts, "sdcf_search_limit", 30)
except Exception:
    limit = 30  # fallback
```

---

## Security Considerations

1. **API Credentials:** Danbooru API key is stored in WebUI's settings (shared.opts). Never log or expose it.
2. **SQL Injection:** All DB queries use parameterized queries (`?` placeholders).
3. **XSS:** All HTML output uses `html.escape()` for user-controlled content.
4. **Path Traversal:** Wildcard export validates paths against discovered wildcard directories only.

---

## Common Issues & Solutions

### Gradio 4 DataFrame Visual Artifacts

Problem: Selection handles, drag bars, or orange outlines appear.

Solution: CSS in `style.css` aggressively hides these:
```css
#sdcf_main_blocks .ag-range-handle,
#sdcf_main_blocks .ag-fill-handle,
#sdcf_main_blocks .ag-selection-handle { ... }
```

### Dropdown Not Triggering on Load

Problem: Gradio 4.x dropdowns don't fire `.change` on initial value.

Solution: Pre-populate `value=` and `choices=` in constructor, not via `.update()`.

### "Send to txt2img" Not Working

Problem: Works only inside actual WebUI (Forge/A1111), not standalone.

Solution: Use standalone mode for UI development, test integration in real WebUI.

---

## File Naming Notes

**Important:** The package is named `wildcard_creator` for historical reasons. Do NOT rename it — the WebUI extension system expects `scripts/wildcard_creator.py` and imports from `wildcard_creator.*`.

---

## Git Conventions

- Database files (`data/characters.db`) are **tracked in git** (pre-packaged data)
- Runtime JSON files (`favorites.json`, `search_history.json`, `recent_viewed.json`) are **gitignored**
- Thumbnail cache (`data/covers/`) is **gitignored**

---

## Useful References

- [Danbooru API Docs](https://danbooru.donmai.us/wiki_pages/api)
- [Gradio Docs](https://gradio.app/docs)
- [AG Grid Themes](https://www.ag-grid.com/javascript-data-grid/themes/)
