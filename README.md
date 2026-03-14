<div align="center">

<img src=".github/sdcf-banner.png" alt="SD Character Finder" width="100%"/>

# 🎭 SD Character Finder

[![SD WebUI](https://img.shields.io/badge/SD_WebUI-A1111%20%7C%20Forge-blue)](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
[![Forge Neo](https://img.shields.io/badge/Forge-Neo-blue)](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Extension for [Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) and [Forge](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)**

</div>

> **Can't remember the exact tag for that specific character? Want to generate an image from a series and discover tags you didn't even know existed? Say no more!** 🦸‍♂️

Your ultimate character encyclopedia directly inside your Stable Diffusion WebUI. Browse over **20,000+ Danbooru characters** without leaving your UI, search by name, tag, or series, preview their thumbnails, and send their perfect prompt tags straight to `txt2img` with a single click!

---

## 📋 Table of Contents

- [What's New](#-whats-new)
- [Changelog](#-changelog)
- [Roadmap](#️-roadmap)
- [Features](#-features)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Credits](#-credits)

---

## 🆕 What's New

### v0.2.0 — Big Cleanup & Polish
- **Clean Series Menu** — We overhauled our database! The series dropdown is now alphabetically organized and free of messy, duplicated text. Filtering by franchise is easier than ever.
- **Pagination & Performance** — Browsing massive queries won't freeze your UI anymore. Navigate results effortlessly using the new Prev/Next buttons.
- **Better Image Previews** — Character images load instantly via your browser, making the app much snappier and immune to backend timeouts.
- **Settings Integration** — Moved all settings gracefully to the native WebUI Settings menu (*Settings -> Options -> SD Character Finder*).

---

## 📖 Changelog

### v0.1.0 — Huge UX Improvements
- **Add to txt2img Button** — A new action button that intelligently appends tags to your existing prompt without wiping it, automatically preventing duplicate words!
- **Live Danbooru Enrichment** — Added an optional section to fetch extra tags dynamically from Danbooru (like clothes, hair, eyes) with neat checkboxes.
- **Clear Button** — Added a simple one-click reset for your search query and results table.

### v0.0.1 — Initial Release
- **Offline Library** — Shipped with an embedded lightweight database containing 20,016 Danbooru characters.
- **Quick Integration** — Works out of the box with AUTOMATIC1111, Forge, and Forge Classic (Neo).
- **Core Functionality** — Search by name or tag, filter by series, view character cards, and send prompts straight to generation.

---

## 🗺️ Roadmap

### v0.1.0 — Huge UX Improvements *(complete)* ✅

### v0.2.0 — Big Cleanup & Polish *(complete)* ✅

### v0.3.0 — Advanced Series Management & User Tags *(planned)*
- Save custom character tags locally.
- Favorites system for quickly accessing your top tier characters.
- Enhanced layout for the extra tags section.

---

## 🎯 Features

> ⭐ = Core Highlights

### 🔍 Browse & Search
- Browse **20,000+ characters** directly inside the WebUI — no tab switching to Danbooru ⭐
- Search by character name, tag, or browse alphabetically by series/franchise
- High-performance offline SQLite database ensures instant search results without internet dependence ⭐
- Pagination system keeps the UI snappy even when returning thousands of results

### 🖼️ Character Info & Preview
- View high-quality character thumbnails instantly
- Expandable **Live Danbooru Tags** menu: fetch extra character-specific tags dynamically from Danbooru (like their clothes, eyes, hair) and check the ones you want to add ⭐
- API key support for Danbooru in settings to bypass anonymous usage limits

### 🚀 One-Click Prompting
- **Send to Generate** — Instantly replaces your current 	xt2img prompt with the character's signature tags
- **Add to txt2img** — Intelligently appends the character tags to your *existing* prompt ⭐
- **Smart Deduplication** — Automatically removes duplicate words when sending tags to your prompt

### ⚙️ Configuration
- Fully integrated with the native WebUI settings menu (Settings -> Options -> SD Character Finder)
- Configure results per page, Danbooru API credentials, and default behaviors
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

## 🚀 Quick Start

1. Go to the new **Danbooru Characters** tab in your WebUI.
2. Type a character name or tag (e.g., miku, saber, lue hair), or pick a series from the **Series Dropdown** (e.g., Arknights).
3. Click **🔍 Search**.
4. Click on any character in the results table to see their preview card and tags.
5. Expand **Extra tags** if you want to pull more specific prompt descriptors directly from the web.
6. Click **➡️ Send to Generate** or **➕ Add to txt2img** to instantly fill your prompt!

---

## 📄 Credits

- **[Danbooru](https://danbooru.donmai.us/)** — For maintaining the incredible tag database and API this project relies upon.
- **[Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui)** — The foundation of the extension.
- **[Forge Neo](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)** by Haoming02

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Made with ❤️ for the Stable Diffusion community

**[Report Bug](https://github.com/eduardoabreu81/sd-character-finder/issues)** • **[Request Feature](https://github.com/eduardoabreu81/sd-character-finder/issues)** • **[Discussions](https://github.com/eduardoabreu81/sd-character-finder/discussions)** • **[☕ Ko-fi](https://ko-fi.com/eduardoabreu81)**

</div>
