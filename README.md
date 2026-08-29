<div align="center">

<img src=".github/sdcf-banner.png" alt="SD Character Finder" width="100%"/>

# 🎭 SD Character Finder

[![SD WebUI](https://img.shields.io/badge/SD_WebUI-A1111%20%7C%20Forge-blue)](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
[![Forge Neo](https://img.shields.io/badge/Forge-Neo-blue)](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Extension for [Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) and [Forge](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)**

</div>

> **Can't remember the exact tag for that specific character? Want to discover a new art style and completely change the look of your generations? Say no more!** 🦸‍♂️

Your ultimate **character encyclopedia** and **artist style discovery** tool directly inside your Stable Diffusion WebUI. Browse **39,006 canonical characters** — backed by 59,508 immutable source representations (20,016 Danbooru + 3,000 e621 + 36,492 AnimaDex) — and **19,800+ unique artist styles** (6,024 Danbooru + 4,032 e621 + 15,879 AnimaDex) without leaving your UI — search characters by name, tag, or series; discover unique art styles with real-time previews; and send both character tags and artist signatures straight to `txt2img` with a single click!

---

## 📋 Table of Contents

- [Character Catalogue v2](#-character-catalogue-v2)
- [What's New](#-whats-new)
- [Changelog](#-changelog)
- [Completed Milestones](#️-completed-milestones)
- [Features](#-features)
- [Installation](#-installation)
- [Upgrading from v0.6.2](#️-upgrading-from-v062)
- [Quick Start](#-quick-start)
- [Credits](#-credits)

---

## 📚 Character Catalogue v2

Since **v0.7.0** the extension ships a canonical character catalogue at
`data/catalog/characters-v2.db` (schema v5). It replaces the flat v1 database:
one canonical character now holds separate Danbooru, e621, and AnimaDex
representations instead of appearing as three unrelated rows.

**39,006 canonical characters** across **39,007 variations**, backed by
**59,508 immutable source representations** (20,016 Danbooru + 3,000 e621 +
36,492 AnimaDex).

### What it changes

- **Source-faithful prompts** — Each representation keeps its own prompt,
  trigger, image, rank, and URL together. Switching source never rewrites prompt
  punctuation or escaping.
- **Search across identities** — Canonical names, official character aliases,
  original work titles, Western/common work aliases, and prompt tags all match.
  Accepted title matches display the official English work name while keeping
  the original transcription and Japanese title searchable.
- **Honest availability filters** — 20,117 characters are confirmed across
  multiple sources and 4 exclusives have completed manual identity review. The
  remaining 18,885 stay labelled **source-only candidates** rather than being
  presented as reviewed exclusives before that review exists.
- **Local prompt overrides** — Prompt edits are saved per representation source
  in `data/user_overrides_v2.json`. Provider prompts inside the catalogue stay
  immutable and can be restored with **Source prompt**.

### e621 series coverage

e621 series metadata is audited offline from the official daily tag, alias,
implication, and wiki exports. **1,762 of the 3,000** e621 representations
resolve to a work, including 1,273 from unambiguous active copyright
implications. The remaining 1,238 stay unresolved on purpose: the legacy
heuristic they replaced mislabelled publishers and generic tags as works, and no
series is better than a wrong one.

### Integrity and recovery

The packaged database is validated against `data/characters.manifest.json` on
startup — SHA-256, schema version, SQLite integrity, relationships, and expected
record counts. An invalid catalogue shows a recovery warning and a
verified-redownload button.

Two controls live under **Settings → SD Character Finder**:

- **Automatically redownload the verified character catalogue when validation
  fails** — restores a missing or damaged database.
- **Redownload the verified character catalogue on next UI startup** — forces
  one verified redownload, then resets itself.

Downloads are restricted to trusted GitHub HTTPS hosts and verified by size and
SHA-256 before being installed atomically. Maintainers rebuilding or
republishing the catalogue should follow
[docs/CATALOG_REBUILD.md](docs/CATALOG_REBUILD.md).

### Disk usage

The tracked databases are never held open by the running extension. Validated
private copies under `data/runtime/` serve searches instead, so Forge's in-app
Git updater can replace packaged databases on Windows. Those copies cost roughly
**94 MB** of additional local disk space and are replaced atomically after
validation on later updates.

---

## 🆕 What's New

### v0.7.0 — Canonical Character Catalogue v2
- **🧬 MAJOR UPDATE — Canonical Catalogue!** Characters are no longer flat rows per source. **39,006 canonical characters** across 39,007 variations now hold **59,508 immutable source representations**, so one character carries its Danbooru, e621, and AnimaDex prompts side by side.
- **Source-Faithful Prompts** ⭐ — Every representation keeps its own prompt, trigger, image, rank, and URL. Switching source never rewrites punctuation or escaping.
- **Smarter Search** — Matches canonical names, official character aliases, original work titles, Western/common aliases, and prompt tags. Official English work titles are displayed while original and Japanese titles stay searchable.
- **Honest Availability Filters** — Confirmed multi-source characters, reviewed exclusives, and source-only candidates are kept distinct instead of being presented as equivalent.
- **e621 Series from Official Exports** — 1,762 of 3,000 e621 representations now resolve to a real work using the official daily exports, replacing a heuristic that mislabelled publishers and generic tags as franchises.
- **Verified Integrity & Recovery** ⭐ — The catalogue is checked against a manifest (SHA-256, schema, SQLite integrity, record counts) on every startup, with one-click verified redownload when that check fails.
- **Forge-Safe Updates** — Packaged databases are never held open at runtime, so Forge's in-app Git updater can replace them on Windows.
- **Per-Source Prompt Overrides** — Local prompt edits are saved per source in `data/user_overrides_v2.json`; provider prompts stay immutable and restorable.

### v0.6.2 — AnimaDex Integration
- **New Source: AnimaDex** — Added 36,492 Anima characters and 15,879 Anima artists to the bundled database.
- **Real Catalogue Numbers** — The extension now ships **39,503 unique characters** (20,016 Danbooru + 3,000 e621 + 36,492 AnimaDex) and **19,817 unique artists** (6,024 Danbooru + 4,032 e621 + 15,879 AnimaDex) after deduplicating overlaps.
- **Source Filter Expanded** — Characters and Artists tabs now include an **Anima** source filter alongside Danbooru and e621.
- **AnimaDex Token Settings** — Added `AnimaDex export token` and `AnimaDex site base URL` settings so users can update the catalogue with their own personal token.
- **Artist Tag Prefix** — Anima artists are tagged with `@artist_name`, matching the prompt format expected by NoobAI/Illustrious models.
- **Single-Image Artist Cards** — Artist cards and preview panel adapt when only one cover image is available (Anima provides one thumbnail per artist).

### v0.6.1 — Artist Tab Reliability & Polish
- **Unified Module Structure** — Characters and Artists now live inside a single **SD Character Finder** tab with internal sub-tabs (matching the CivitAI Browser pattern), cleaning up the top-level tab bar.
- **Pagination Fixed** — Prev/Next and page jump now work correctly in the Artists tab. The root cause was Gradio `.then()` chains not passing updated `gr.State` values between handlers.
- **Settings Now Reflect Live** — Changes to artist gallery columns, thumbnail size, and results-per-page in WebUI Settings are picked up immediately on the next search or page change.
- **No More Image Cropping** — Artist cards switched to `object-fit: contain` so images display fully at any thumbnail size, with a clean dark background for letterboxing.
- **Status Field Fixed** — The Status textbox no longer shows the raw artist tag after clicking **Add to txt2img**; it correctly displays the confirmation message.

### v0.6.0 — Artist Style Discovery
- **🎨 MAJOR UPDATE — Artist Style Browser!** Discover and apply **19,800+ unique artist styles** (6,024 Danbooru + 4,032 e621 + 15,879 AnimaDex). Browse visually, add the artist's tag with one click, and watch the magic happen — your generation's art style transforms instantly.
- **Dual-Preview Cards** ⭐ — Every artist shows two side-by-side examples (e.g., *Tifa Lockhart* and *Harry Potter* both rendered in that artist's unique style) so you can instantly see how their drawing technique looks applied to different subjects before adding it to your prompt.
- **Separate Settings** — Artists have their own pagination limit, thumbnail size, and column count settings independent from characters.
- **Security Improvements** — Fixed potential vulnerabilities in gallery rendering and image downloads.

---

## 📖 Changelog

### v0.7.0 — Canonical Character Catalogue v2
- **New Catalogue** — `data/catalog/characters-v2.db` (schema v5) with canonical characters, variations, and per-source representations. The legacy `data/characters.db` is never opened at runtime and is removed after the first restart.
- **Manifest Validation** — `data/characters.manifest.json` pins size, SHA-256, schema version, SQLite integrity, relationships, and record counts.
- **Verified Recovery** — Catalogue redownload is restricted to trusted GitHub HTTPS hosts, verified by size and digest, and installed atomically. The artifact is hosted on release assets so recovery never depends on repository history.
- **Runtime Copies** — Character and artist databases are served from validated private copies under `data/runtime/`, unblocking Forge's Windows Git updater.
- **e621 Series Audit** — Offline audit against the official daily tag, alias, implication, and wiki exports; 1,273 links come from unambiguous active copyright implications.
- **Reproducible Rebuild** — The AnimaDex character export is tracked and the full rebuild chain is documented in [docs/CATALOG_REBUILD.md](docs/CATALOG_REBUILD.md).
- **Test Suite** — 46 automated tests covering the builder, the e621 audit, catalogue health, legacy migration, and recovery.
- **Search Controls Layout** — Search, Clear Search, and Clear All are now direct `gr.Row` children using `size="lg"` and `equal_height=True`, fixing alignment on Forge Neo.
- **Removed** — `data/anima_characters.db` is no longer shipped; its data lives in the v2 catalogue.

### v0.6.1 — Artist Tab Reliability & Polish
- **Unified Tab Structure** — Artists is now a sub-tab inside "SD Character Finder" instead of a separate top-level tab.
- **Pagination Fix** — Removed broken Gradio `.then()` chains; pagination handlers now compute new pages internally like the Characters tab.
- **Dynamic Settings** — Artist gallery columns, thumbnail size, and search limit are read fresh on every event instead of cached at build time.
- **Image Crop Fix** — `object-fit: contain` replaces `cover` so artist previews show fully at any size.
- **Status Message Fix** — JavaScript handlers no longer overwrite the Python confirmation message with the raw tag.

### v0.5.3 — Hotfix: Startup Crash & Database Lock
- **Startup Crash Fix** — Fixed a `NameError` crash that prevented the Gradio extension from initializing on remote WebUI instances (like RunPod) after the recent pagination updates.
- **Database Lock Fix** — Disabled WAL mode and added an automatic cleanup routine for orphaned `.db-wal` and `.db-shm` files. This permanently prevents the `database disk image is malformed` error that occurred when updating the extension via `git pull` on remote servers.
- **Gallery History Click** — Fixed issue where clicking a character in the "Recently Viewed" list wouldn't load their details.

### v0.5.2 — History Pagination, Auto-Select & DB Series Rescue
- **DB Series Rescue** — Automatically fixed 709 popular characters (including Konosuba, JoJo, Re:Zero) that were missing their franchise metadata entirely by extracting and standardizing their 2nd copyright tag.
- **Recently Viewed Extended** — Increased history retention limit from 20 to 100 characters and added independent, fully functional pagination controls exclusively inside the "Recently Viewed" tab.
- **Auto-Select Search Results** — Submitting a search now automatically selects and loads the preview image and attributes of the first resulting character, saving you an extra click.

### v0.5.1 — Global Pagination & Forge State Saving
- **Global Pagination** — Pagination controls (top and bottom) are now truly global, existing outside the "Search Results" tab. This allows seamless page navigation across any visible tab (Search, History, etc.) without losing context.
- **Forge State Saving** — Added permanent `elem_id` hooks to all key inputs (Search, Series, Dropdowns). This allows AUTOMATIC1111/Forge's native "Save UI Defaults" feature to reliably serialize and restore your exact filter state across reboots.
- **Search Reset Fixes** — Fixed a bug where clicking "Clear Search" or "Clear All" would break the Series dropdown by setting it to `None`. It now correctly resets back to the `"All"` state.

### v0.5.0 — Favorites, History & UI Polish
- Added visual and database-backed "Favorites" marking logic (`data/favorites.json`).
- Added full "Recent Searches" and "Favorites" isolated tabs.
- Custom Svelte DOM styling to patch Gradio 4 Dataframe artifacts (hidden drag rows, clean outlines).
- Completely removed startup automatic scraping from UI entrypoints. `data/characters.db` serves as authority unless updated actively by git/scripts.
- Custom `-webkit-scrollbar` UI overrides integrated with WebUI's core variable themes.

### v0.4.2 — Background Scraping Removed
- Extracted automated scraping triggers on extension load. Fixed startup freezing loops dynamically.

### v0.4.1 — Reliability, Dedupe Control & Startup Sync
- Added `Add to txt2img: Deduplicate incoming tags` option to native WebUI Settings.
- `Add to txt2img` now supports both modes: deduplicated append and raw append.
- Improved startup auto-scrape consistency for both Danbooru and e621 sources.
- Hardened SQLite runtime behavior (WAL, busy timeout, synchronous normal).
- Improved gallery performance by reusing requests session and caching data URIs in memory.

### v0.4.0 — Unified Database, e621 Support & UX Boosts
- **e621 Integration** — Unified database now includes 3,000+ e621 characters alongside Danbooru.
- **Source Filter + Badges** — Added Danbooru/e621/both filtering and visual source badges.
- **Recently Viewed Panel** — Added quick-access history for the most recently opened characters.
- **Advanced Multi-Term Search** — Search now applies AND logic for multiple keywords.
- **Background Auto-Scraper** — Startup recovery flow for missing/incomplete datasets.

### v0.3.2 — Gallery Customization & Auto-Switch
- Added WebUI settings for gallery thumbnail size and cards per row.
- Added automatic tab switch to `txt2img` when using Send/Add actions.

### v0.3.1 — Stable Gallery Cards + Expandable Preview
- **Custom Card Gallery** — Replaced Gradio Gallery rendering with a custom HTML card grid for predictable desktop/mobile behavior.
- **Reliable Card Selection** — Clicking a card now consistently loads character data and tags.
- **Large Expandable Preview** — Side preview now includes an in-image hint (`Click to expand`) and opens a large modal/lightbox when clicked.
- **Safer Pagination Control** — Results-per-page is configurable in Settings with a stable range (`5..30`, hard cap at `30`).

### v0.3.0 — Visual Search Gallery Mode
- **Visual Browser** — Added a brand new "Gallery View" tab to the search results! You can now toggle between seeing results as a compact List or a visual Grid showing thumbnails of all characters simultaneously. Powered by safe, fast CDN links (no Danbooru rate-limits!).

### v0.2.3 — Gradio 3 Backward Compatibility
- Fixed an issue causing crashes on Forge Classic due to unsupported js keyword arguments by enforcing _js when invoked under older Gradio runtimes.

### v0.2.2 — Forge Classic Startup Fix (Part 2)
- **Settings Parser Fix** — Explicitly mapped `float` config values to Gradio Slider components to prevent startup crashes on older or parallel forks (e.g. Forge Classic) where global UI parsing failed during boot.

### v0.2.1 — Forge Classic Startup Fix (Part 1)
- **Settings Parser Fix** — Explicitly mapped `float` config values to Gradio Slider components to prevent startup crashes on older or parallel forks.

### v0.2.0 — Beautiful Layout, Categories & Logic Override
- **Sleek UI Remaster** — Fully remade the interface taking advantage of horizontal layout capabilities. The character attributes and thumbnail now sit cleanly on the left while results populate on your right.
- **Categorical Extra Tags** — Now, clicking "Fetch Extra Tags" neatly sorts all live-fetched Danbooru attributes into distinct checkboxes (Character, Series, General, Meta).
- **NovelAI Tag Ordering** — The algorithm behind tag injections now flawlessly forces ideal syntax orders (`1girl`, `character`, `series`, `everything else`) for much stronger promping results.
- **User Overrides Persistence** — Your local changes to labels and DB saves now persist accurately to a local `user_overrides.json`, keeping you completely safe from `git pull` overwrites when updating the tool!
- **Target Folder Cleaner** — Cleaned up wildcards output. The extension now grabs its default Wildcard backup location directly from a global WebUI Setting option!

### v0.1.0 — Huge UX Improvements
- **Add to txt2img Button** — A new action button that intelligently appends tags to your existing prompt without wiping it, automatically preventing duplicate words!
- **Live Danbooru Enrichment** — Added an optional section to fetch extra tags dynamically from Danbooru (like clothes, hair, eyes) with neat checkboxes.
- **Clear Button** — Added a simple one-click reset for your search query and results table.

### v0.0.1 — Initial Release
- **Offline Library** — Shipped with an embedded lightweight database containing 20,016 Danbooru characters.
- **Quick Integration** — Works out of the box with AUTOMATIC1111, Forge, and Forge Classic (Neo).
- **Core Functionality** — Search by name or tag, filter by series, view character cards, and send prompts straight to generation.

---

## 🗺️ Completed Milestones

### v0.1.0 — Huge UX Improvements ✅

### v0.2.0 — UI Overhaul, Live API & Offline Caching ✅
- Total layout overhaul (Split screen logic, Thumbnail on the left).
- Better structure separating Danbooru 'Extra tags' dynamically by category (Character, Copyright, General, Artist and Meta).
- Accurate default tag ordering mimicking NovelAI's preferred weighting style.
- Full internal DB persistency using local files to avoid conflicts.
- Local Base64 Image Caching in `data/covers/` directory to prevent bandwidth usage and timeouts.

### v0.3.1 — Visual Search Stabilization ✅
- Replaced unstable Gradio gallery layout with custom HTML card grid.
- Added card-click selection bridge with consistent behavior across desktop/mobile.
- Added large modal preview (`Click to expand`) from side preview.

### v0.3.2 — Gallery Customization & Auto-Switch ✅
- Exposed thumbnail size and cards-per-row options in WebUI Settings.
- Added automatic tab switching to `txt2img` when sending or appending tags.

### v0.4.0 — e621 Support & Search UX ✅
- Optional e621 support (Unified Database with >3000 characters & Source Filter).
- Recently Viewed history panel for quick character hopping.
- Multi-term `AND` search logic.

### v0.5.0 — Favorites, History & UI Polish ✅
- Favorites system with JSON persistence.
- Recently Viewed history panel for quick character hopping.
- Global pagination controls across all tabs.
- Forge "Save UI Defaults" support.

### v0.6.0 — Artist Style Discovery ✅
- **Artist Style Browser** with dual-preview cards.
- Visual style discovery with side-by-side previews.
- One-click artist tag injection into prompts.
- Separate pagination and display settings for artists.

### v0.6.1 — Artist Tab Polish ✅
- Unified sub-tab structure (Characters + Artists inside one module).
- Live pagination and settings reflection.
- Clean image rendering without cropping.
- Stable status messages after add/copy actions.

### v0.7.0 — Canonical Character Catalogue v2 ✅
- Canonical character / variation / representation model with immutable per-source prompts.
- Manifest-validated catalogue with verified redownload and recovery controls.
- Forge-safe runtime database copies on Windows.
- Offline e621 series audit from the official daily exports.
- Reproducible rebuild chain and a 46-test automated suite.

---

## 🎯 Features

> ⭐ = Core Highlights

### 🔍 Browse Characters
- Browse **39,006 canonical characters** backed by 59,508 source representations (20,016 Danbooru + 3,000 e621 + 36,492 AnimaDex) directly inside the WebUI — no tab switching! ⭐
- Search by character name, tag, or browse alphabetically by series/franchise
- **Switch source per character** — read the Danbooru, e621, or AnimaDex representation of the same character without leaving the card, each with its own untouched prompt ⭐
- Search also matches official character aliases, original work titles, and Western/common work aliases, not just the display name
- Filter by availability: confirmed multi-source characters, reviewed exclusives, or source-only candidates
- Use multiple keywords for precise filtering (e.g., `miku vocaloid` ensures both terms exist)
- Track your session with **Recent searches** and **Favorites** Tabs directly synced local-first. ⭐
- High-performance offline SQLite database ensures instant search results without internet dependence ⭐
- Pagination system keeps the UI snappy even when returning thousands of results

### 🎨 Discover Artist Styles *(NEW in v0.6.0)*
- Browse **19,800+ unique artist styles** (6,024 Danbooru + 4,032 e621 + 15,879 AnimaDex) in a dedicated Artists tab ⭐
- **Dual-preview cards** — Every artist shows two side-by-side examples (e.g., Tifa Lockhart style + Harry Potter style) so you can visually compare their drawing technique before applying it ⭐
- **Visual discovery** — Don't know an artist's name? Just browse the gallery and "scroll until something clicks" — thumbnails make discovering new styles effortless
- **One-click apply** — Click any card, then hit **Add to txt2img** to inject `by artist_name` straight into your prompt
- **Favorites for artists** — Save your favorite art styles for quick access, separate from character favorites
- Separate pagination, thumbnail size, and column settings for the Artists gallery

### 🖼️ Character Info & Preview
- View high-quality character thumbnails instantly (with color-coded Source Badges).
- Stable visual card grid in **Gallery View** with responsive layout (desktop and mobile).
- **Recently Viewed** panel tracks your last clicked characters and artists.
- Click any card to load details and prompt tags.
- Side preview supports **Click to expand** and opens a large modal image.
- Expandable **Live Danbooru Tags** menu: dynamically fetch extra character-specific tags from Danbooru (like clothes, eyes, hair) separated into explicit selectable Checkboxes by Category ⭐
- Automatically sorts appended web-tags following optimal generation standards (NovelAI style formatting).
- Clean, translation-ready interface integrating straight into A1111/Forge standard inputs.

### 🚀 One-Click Prompting
- **Send to Generate** — Instantly replaces your current `txt2img` prompt and **automatically switches you to the tab**.
- **Add to txt2img** — Intelligently appends tags to your *existing* prompt ⭐
- **Smart Deduplication** — Automatically removes duplicate words when enabled in Settings
- Supports both **Character tags** and **Artist style tags** seamlessly

### ⚙️ Configuration
- Fully integrated with the native WebUI settings menu (Settings -> Options -> SD Character Finder)
- Configure results per page for **Characters** and **Artists** independently
- **Thumbnail sizes, cards per row**, deduplication behavior, Danbooru API credentials, and default behaviors
- Fast, lightweight, and completely localized

---

## 📦 Installation

### Inside SD WebUI (Recommended)

1. Open your WebUI and go to the **Extensions** tab.
2. Click on the **Install from URL** sub-tab.
3. Paste: https://github.com/eduardoabreu81/sd-character-finder
4. Click **Install**.
5. Go to the **Installed** sub-tab and click **Apply and restart UI**.

> ⚠️ Compatible with AUTOMATIC1111, Forge, and Forge Classic / Neo.

---

## ⬆️ Upgrading from v0.6.2

Update normally — **Extensions → Check for updates → Apply and restart UI**, or
`git pull` inside the extension folder. No manual steps are required.

What happens on the first v0.7.0 start:

1. The v2 catalogue is validated against its manifest and a private runtime copy
   is activated.
2. The old `data/characters.db` is kept byte-identical through the update purely
   as a bridge for the Forge updater. After the restart, v2 recognizes it by
   checksum and removes it. **It is never used as a fallback.** Git then reports
   the file as a local deletion, which is expected and does not affect further
   updates.
3. `data/anima_characters.db` is no longer shipped and is removed; its data now
   lives in the v2 catalogue.

Favorites, recent history, and existing user overrides are preserved. New prompt
edits are stored per representation source in `data/user_overrides_v2.json`.

> ⚠️ **One-time Windows caveat.** If the old **Save Danbooru Tag** behaviour
> modified the tracked `data/characters.db`, Git has to restore a dirty file
> that the running WebUI still holds open. That installation needs one final
> WebUI shutdown before the update applies. Later updates use private runtime
> copies and do not have this limitation.

---

## 🚀 Quick Start

1. Go to the new **Characters** tab in your WebUI.
2. Type a character name or tag (e.g., miku, saber, blue hair), or pick a series from the **Series Dropdown** (e.g., Arknights).
3. Click **🔍 Search**.
4. Click on any character card to see their preview and tags.
5. Click **➡️ Send to Generate** or **➕ Add to txt2img** to instantly fill your prompt!

### 🎨 Discovering Artist Styles
1. Switch to the **Artists** tab.
2. Browse the gallery visually — each card shows two style examples side-by-side.
3. Found a style you like? Click the card to load the artist's tag.
4. Click **➕ Add to txt2img** to inject `by artist_name` into your prompt.
5. Combine character + artist for unique generations!

---

## 📄 Credits

- **[Danbooru](https://danbooru.donmai.us/)** — For maintaining the incredible tag database and API this project relies upon.
- **[NoobAI-XL / Danbooru Character](https://www.downloadmost.com/NoobAI-XL/danbooru-character/)** — Inspiration and reference for Danbooru character tagging.
- **[Danbooru-Tags-Sort-Exporter](https://github.com/Takenoko3333/Danbooru-Tags-Sort-Exporter)** by Takenoko3333 — Inspiration for the NovelAI-like tag sorting logic.

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Made with ❤️ for the Stable Diffusion community

**[Report Bug](https://github.com/eduardoabreu81/sd-character-finder/issues)** • **[Request Feature](https://github.com/eduardoabreu81/sd-character-finder/issues)** • **[Discussions](https://github.com/eduardoabreu81/sd-character-finder/discussions)** • **[☕ Ko-fi](https://ko-fi.com/eduardoabreu81)**

</div>
