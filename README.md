<div align="center">

<img src=".github/sdcf-banner.png" alt="SD Character Finder Header" width="100%">

[![SD WebUI](https://img.shields.io/badge/SD_WebUI-A1111%20%7C%20Forge-blue)](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
[![Forge Neo](https://img.shields.io/badge/Forge-Neo-blue)](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

# 🎭 SD Character Finder

<div align="center">

> **Your ultimate character encyclopedia directly inside Stable Diffusion WebUI.**

</div>

Browse **20,000+ Danbooru characters** without leaving your UI. Search by name, tag, or series, preview their thumbnails, and send their perfect prompt tags straight to `txt2img` with a single click!

---

## ✨ Why use this extension?

- **Huge Offline Database:** Browse over 20,000 characters from popular series (Pokémon, Fate, Touhou, Arknights, Genshin Impact, etc.) without relying on slow internet searches.
- **Smart Search & Filters:** Find your favorite character by typing their name or searching alphabetically through our organized Series dropdown.
- **One-Click Prompting:** Click **Send to Generate** to replace your prompt, or **Add to txt2img** to smoothly append the character tags to your existing prompt intelligently.
- **Live Danbooru Tags (Optional):** Want more details in your prompt? Automatically fetch extra character-specific tags directly from Danbooru (like their clothes, eyes, hair) and check the ones you want to add.
- **Fast & Lightweight:** Results are paginated so your WebUI never freezes, and images load instantly!

---

## 📦 Installation

### Inside SD WebUI (Recommended)

1. Open your WebUI and go to the **Extensions** tab.
2. Click on the **Install from URL** sub-tab.
3. Paste this URL into the first field:
   `https://github.com/eduardoabreu81/sd-character-finder`
4. Click **Install**.
5. Go to the **Installed** sub-tab and click **Apply and restart UI**.

*(Compatible with AUTOMATIC1111, Forge, and Forge Classic / Neo)*

---

## 🚀 Quick Start

1. Go to the new **Danbooru Characters** tab in your WebUI.
2. Type a character name or tag (e.g., `miku`, `saber`, `blue hair`).
3. Alternatively, pick a series from the Series Dropdown (e.g., `Arknights`).
4. Click **🔍 Search**.
5. Click on any character in the results table to see their preview card and tags.
6. Click **➡️ Send to Generate** or **➕ Add to txt2img** to instantly fill your prompt!

---

## ⚙️ Configuration

You can tweak the extension settings natively in your WebUI!
Go to **Settings -> Options -> SD Character Finder**.
Here you can adjust:
- How many characters show up per page.
- Your Danbooru API credentials (optional, only needed if you heavily use the Live Tags search feature and want to bypass anonymous limits).

---

## 🆕 Recent Updates

**v0.2.0 - Big Cleanup & Polish**
- **Clean Series Menu:** We overhauled our database! The series menu is now alphabetically organized and free of messy, duplicated text. Filtering by franchise is easier than ever.
- **Pagination:** Browsing massive queries won't freeze your UI anymore. Use the new Prev/Next buttons!
- **Better Image Previews:** Character images load instantly via your browser, making the app much snappier.
- **Settings Tab:** Moved all settings gracefully to the native WebUI Settings menu.

*(For detailed technical logs and patch notes, check the `docs/` folder)*
