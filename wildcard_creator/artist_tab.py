"""
artist_tab.py — Artist Style References tab for SD Character Finder.

This module is self-contained: it builds the entire Artists tab UI,
handles search/gallery/preview/events, and injects tags into txt2img
via client-side JavaScript.

Usage (from ui.py):
    from wildcard_creator.artist_tab import build_artist_tab
    with gr.Tab("🎨 Artists", id="tab_artists"):
        artist_components = build_artist_tab()
"""

from __future__ import annotations

import base64
import concurrent.futures
import html
import logging
from collections import OrderedDict
from pathlib import Path

import gradio as gr
import requests

from wildcard_creator.artist_db import get_artist_db
from wildcard_creator.artist_favorites import get_artist_favorites_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config / cache
# ---------------------------------------------------------------------------

COVER_CACHE_MAX = 500
http_session = requests.Session()
http_session.headers.update({"User-Agent": "SDCharacterFinder/1.0"})

_cover_data_uri_cache: OrderedDict[int, str] = OrderedDict()


def _cache_get(artist_id: int) -> str | None:
    val = _cover_data_uri_cache.get(artist_id)
    if val is not None:
        _cover_data_uri_cache.move_to_end(artist_id)
    return val


def _cache_set(artist_id: int, data_uri: str) -> None:
    _cover_data_uri_cache[artist_id] = data_uri
    _cover_data_uri_cache.move_to_end(artist_id)
    while len(_cover_data_uri_cache) > COVER_CACHE_MAX:
        _cover_data_uri_cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_settings_opt(key: str, default):
    try:
        from modules import shared
        if hasattr(shared, "opts") and hasattr(shared.opts, key):
            return getattr(shared.opts, key)
    except Exception:
        pass
    return default


def _is_safe_url(url: str) -> bool:
    """Validate URL against SSRF."""
    try:
        from urllib.parse import urlparse
        import socket

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        allowed = (
            ".donmai.us",
            ".e621.net",
            "e621.net",
            "downloadmost.com",
        )
        if not any(hostname == s or hostname.endswith(s) for s in allowed):
            return False
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in addr_info:
                ip = sockaddr[0]
                if ip.startswith("127.") or ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("169.254."):
                    return False
                if ip.startswith("172."):
                    parts = ip.split(".")
                    if len(parts) >= 2 and 16 <= int(parts[1]) <= 31:
                        return False
                if ":" in ip:
                    if ip.startswith("::1") or ip.startswith("fe80:") or ip.startswith("fc") or ip.startswith("fd"):
                        return False
        except Exception:
            pass
        return True
    except Exception:
        return False


def _download_cover(url: str, artist_id: int) -> str | None:
    """Download cover, cache as base64 data URI, return the data URI or original URL."""
    if not url or not artist_id:
        return None

    cached = _cache_get(artist_id)
    if cached:
        return cached

    repo_root = Path(__file__).resolve().parent.parent
    covers_dir = repo_root / "data" / "artist_covers"
    covers_dir.mkdir(parents=True, exist_ok=True)

    cov_path = covers_dir / f"{artist_id}.jpg"
    if not cov_path.exists():
        try:
            if _is_safe_url(url):
                resp = http_session.get(url, timeout=5)
                if resp.status_code == 200:
                    cov_path.write_bytes(resp.content)
        except Exception:
            pass

    if cov_path.exists():
        try:
            img_b64 = base64.b64encode(cov_path.read_bytes()).decode("ascii")
            data_uri = f"data:image/jpeg;base64,{img_b64}"
            _cache_set(artist_id, data_uri)
            return data_uri
        except Exception:
            return url
    return url


def _build_gallery_html(
    artists: list,
    fav_db,
    cols: int = 3,
    mobile_cols: int = 2,
    thumb_size: int = 260,
) -> str:
    """Render artist cards with dual preview images."""
    if not artists:
        return "<div class='sdcf-char-gallery sdcf-artist-gallery'><div class='civmodellist'><p style='padding:20px;text-align:center;color:var(--body-text-color-subdued)'>No artists found.</p></div></div>"

    def fetch_covers(artist):
        a_id = artist["id"]
        img1 = _download_cover(artist.get("image_url_1"), a_id)
        img2 = _download_cover(artist.get("image_url_2"), a_id)
        return (a_id, img1 or "", img2 or "")

    covers = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(artists))) as executor:
        for a_id, img1, img2 in executor.map(fetch_covers, artists):
            covers[a_id] = (img1, img2)

    cards_html = []
    for artist in artists:
        a_id = artist["id"]
        name = artist.get("display_name") or artist.get("name") or "Unknown"
        tag = artist.get("tag") or artist.get("name") or ""
        ref_count = artist.get("ref_count", 0)
        source = artist.get("source", "danbooru")
        img1, img2 = covers.get(a_id, ("", ""))

        safe_name = html.escape(name)
        safe_tag = html.escape(tag)
        safe_source = html.escape(source)
        safe_img1 = html.escape(img1, quote=True)
        safe_img2 = html.escape(img2, quote=True)

        is_fav = fav_db.is_favorite(a_id)
        fav_html = "<span class='sdcf-fav-badge'>❤️</span>" if is_fav else ""

        onclick_js = (
            f"document.getElementById('sdcf_artist_gallery_click_idx').value='{a_id}';"
            "document.getElementById('sdcf_artist_gallery_click_idx').dispatchEvent(new Event('input',{bubbles:true}));"
            "document.getElementById('sdcf_artist_gallery_click_idx').dispatchEvent(new Event('change',{bubbles:true}));"
            "return false;"
        )
        safe_onclick = html.escape(onclick_js, quote=True)

        cards_html.append(
            f"""
            <div class='civmodelcard' role='button' tabindex='0' onclick="{safe_onclick}" onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();this.click();}}">
                <figure>
                    {fav_html}
                    <div class='sdcf-ref-count'>{ref_count:,} refs</div>
                    <div class='sdcf-badge sdcf-badge-{safe_source}'>{safe_source}</div>
                    <img src='{safe_img1}' alt='{safe_name} - preview 1' loading='lazy' />
                    <img src='{safe_img2}' alt='{safe_name} - preview 2' loading='lazy' />
                    <figcaption>{safe_name}</figcaption>
                </figure>
            </div>
            """
        )

    return (
        f"<div id='sdcf_artist_gallery_html' class='sdcf-char-gallery sdcf-artist-gallery' style='--sdcf-artist-cols:{cols};--sdcf-artist-mobile-cols:{mobile_cols};--sdcf-artist-thumb-size:{thumb_size}px'><div class='civmodellist'>"
        + "".join(cards_html)
        + "</div></div>"
    )


def _build_preview_html(artist: dict | None, is_favorite: bool = False) -> str:
    """Build the side preview panel for a selected artist."""
    if not artist:
        return "<div class='sdcf-preview-empty'>No artist selected</div>"

    name = artist.get("display_name") or artist.get("name") or "Unknown"
    tag = artist.get("tag") or artist.get("name") or ""
    ref_count = artist.get("ref_count", 0)
    source = artist.get("source", "danbooru")
    a_id = artist.get("id", 0)

    img1 = _download_cover(artist.get("image_url_1"), a_id) or ""
    img2 = _download_cover(artist.get("image_url_2"), a_id) or ""

    safe_name = html.escape(name)
    safe_tag = html.escape(tag)
    safe_source = html.escape(source)
    safe_img1 = html.escape(img1, quote=True)
    safe_img2 = html.escape(img2, quote=True)

    fav_badge = "<div class='sdcf-badge sdcf-badge-favorite sdcf-preview-favorite'>favorite</div>" if is_favorite else ""
    src_badge = f"<div class='sdcf-badge sdcf-badge-{safe_source} sdcf-preview-source'>{safe_source}</div>"

    return f"""
<div class='sdcf-preview-wrap sdcf-artist-preview-wrap'>
    {fav_badge}
    {src_badge}
    <div class='sdcf-artist-preview-images'>
        <img src='{safe_img1}' alt='{safe_name} - style preview 1' />
        <img src='{safe_img2}' alt='{safe_name} - style preview 2' />
    </div>
    <div class='sdcf-artist-preview-info'>
        <div class='sdcf-artist-preview-name'>{safe_name}</div>
        <div class='sdcf-artist-preview-tag'>{safe_tag}</div>
        <div class='sdcf-artist-preview-refs'>{ref_count:,} reference images</div>
    </div>
</div>
"""


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_artist_tab():
    """Build and return all Gradio components for the Artists tab."""

    # -- Settings defaults --
    raw_limit = _get_settings_opt("sdcf_search_limit", 30)
    raw_thumb_size = _get_settings_opt("sdcf_artist_gallery_thumb_size", 260)
    raw_gallery_columns = _get_settings_opt("sdcf_artist_gallery_columns", 3)
    results_per_page = max(5, min(int(raw_limit), 60))
    thumb_size = max(80, min(int(raw_thumb_size), 400))
    gallery_columns = max(1, min(int(raw_gallery_columns), 6))
    mobile_columns = max(1, min(gallery_columns, 2))

    # -- States --
    artist_page_state = gr.State(1)
    artist_total_pages_state = gr.State(1)
    artist_results_state = gr.State([])
    artist_selected_id_state = gr.State(None)

    # -- Search row --
    with gr.Row():
        artist_search = gr.Textbox(
            label="Search Artists",
            placeholder="e.g. hammer, ebifurya...",
            lines=1,
            elem_id="sdcf_artist_search",
        )
        artist_source_filter = gr.Dropdown(
            label="Source",
            choices=["all", "danbooru", "e621"],
            value="all",
            elem_id="sdcf_artist_source",
        )
        btn_artist_search = gr.Button("🔍 Search", variant="primary")
        btn_artist_clear = gr.Button("🗑️ Clear")

    # -- Gallery --
    artist_gallery = gr.HTML(
        value="<div id='sdcf_artist_gallery_html' class='sdcf-char-gallery sdcf-artist-gallery'><div class='civmodellist'></div></div>",
        label="Artists",
        elem_id="sdcf_artist_gallery_html",
    )
    artist_gallery_click_idx = gr.Textbox(value="-1", visible=False, elem_id="sdcf_artist_gallery_click_idx")

    # -- Pagination --
    with gr.Row():
        with gr.Column(scale=4):
            pass
        with gr.Column(scale=1, min_width=100):
            btn_artist_prev = gr.Button("◀ Prev", interactive=True)
        with gr.Column(scale=1, min_width=120):
            with gr.Row():
                artist_page_jump = gr.Number(value=1, label="Page", precision=0, show_label=False, min_width=50)
            artist_page_indicator = gr.Markdown("<div style='text-align: center; margin-top: 8px;'>Page 1 of 1</div>")
        with gr.Column(scale=1, min_width=100):
            btn_artist_next = gr.Button("Next ▶", interactive=True)

    gr.Markdown("---\n*Click an artist card above to load details.*")

    # -- Artist detail panel --
    with gr.Row():
        with gr.Column(scale=2):
            artist_name_out = gr.Textbox(label="Artist", interactive=False, lines=1)
            artist_tag_out = gr.Textbox(
                label="Tag for prompt",
                lines=1,
                interactive=True,
                elem_id="sdcf_artist_tag_out",
            )
            with gr.Row():
                btn_artist_add = gr.Button("➕ Add to txt2img", size="lg")
                btn_artist_copy = gr.Button("📋 Copy Tag", size="lg")
            with gr.Row():
                btn_artist_favorite = gr.Button("🤍 Favorite", size="lg")
            artist_status = gr.Textbox(visible=True, interactive=False, label="Status")

        with gr.Column(scale=1, min_width=360):
            artist_preview = gr.HTML(
                value="<div class='sdcf-preview-empty'>No artist selected</div>",
                label="Preview",
                elem_id="sdcf_artist_preview",
            )

    # -----------------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------------

    def get_js_kw(js_code: str):
        """Return js= or _js= depending on Gradio version."""
        try:
            import gradio
            gv = tuple(int(x) for x in gradio.__version__.split(".")[:2])
            if gv >= (4, 0):
                return {"js": js_code}
        except Exception:
            pass
        return {"_js": js_code}

    def do_artist_search(query, source, page):
        db = get_artist_db()
        fav_db = get_artist_favorites_db()
        limit = results_per_page
        offset = (page - 1) * limit

        total = db.count(query=query, source=source)
        rows = db.search(query=query, source=source, limit=limit, offset=offset)
        results = [dict(r) for r in rows]
        total_pages = max(1, (total + limit - 1) // limit)

        gallery_html = _build_gallery_html(
            results,
            fav_db,
            cols=gallery_columns,
            mobile_cols=mobile_columns,
            thumb_size=thumb_size,
        )

        return [
            gallery_html,
            results,
            gr.update(value=page),
            gr.update(value=total_pages),
            f"<div style='text-align: center; margin-top: 8px;'>Page {page} of {total_pages}</div>",
        ]

    def on_artist_select(artist_id_str, results):
        artist_id = int(artist_id_str) if artist_id_str and artist_id_str != "-1" else None
        if not artist_id or not results:
            return [
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value="<div class='sdcf-preview-empty'>No artist selected</div>"),
                gr.update(value="No artist selected"),
                None,
                gr.update(value="🤍 Favorite"),
            ]

        artist = None
        for r in results:
            if r.get("id") == artist_id:
                artist = r
                break

        if not artist:
            return [
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value="<div class='sdcf-preview-empty'>No artist selected</div>"),
                gr.update(value="Artist not found"),
                None,
                gr.update(value="🤍 Favorite"),
            ]

        fav_db = get_artist_favorites_db()
        is_fav = fav_db.is_favorite(artist_id)
        preview_html = _build_preview_html(artist, is_favorite=is_fav)

        return [
            gr.update(value=artist.get("display_name", "") or artist.get("name", "")),
            gr.update(value=artist.get("tag", "") or artist.get("name", "")),
            gr.update(value=preview_html),
            gr.update(value=""),
            artist_id,
            gr.update(value="❤️ Unfavorite" if is_fav else "🤍 Favorite"),
        ]

    def toggle_artist_favorite(artist_id):
        if not artist_id:
            return gr.update(value="⚠️ No artist selected")
        fav_db = get_artist_favorites_db()
        is_fav = fav_db.toggle(artist_id)
        return gr.update(value="❤️ Unfavorite" if is_fav else "🤍 Favorite")

    def do_artist_add(tag):
        if not tag:
            return gr.update(value="⚠️ No tag to add")
        return gr.update(value="✅ Added to txt2img")

    def do_artist_copy(tag):
        if not tag:
            return gr.update(value="⚠️ No tag to copy")
        return gr.update(value="✅ Copied to clipboard")

    # -- Event wiring --

    btn_artist_search.click(
        fn=do_artist_search,
        inputs=[artist_search, artist_source_filter, artist_page_state],
        outputs=[artist_gallery, artist_results_state, artist_page_state, artist_total_pages_state, artist_page_indicator],
    )

    artist_search.submit(
        fn=do_artist_search,
        inputs=[artist_search, artist_source_filter, artist_page_state],
        outputs=[artist_gallery, artist_results_state, artist_page_state, artist_total_pages_state, artist_page_indicator],
    )

    btn_artist_clear.click(
        fn=lambda: ["", "all", 1],
        inputs=[],
        outputs=[artist_search, artist_source_filter, artist_page_state],
    ).then(
        fn=do_artist_search,
        inputs=[artist_search, artist_source_filter, artist_page_state],
        outputs=[artist_gallery, artist_results_state, artist_page_state, artist_total_pages_state, artist_page_indicator],
    )

    btn_artist_prev.click(
        fn=lambda p, tp: max(1, p - 1),
        inputs=[artist_page_state, artist_total_pages_state],
        outputs=[artist_page_state],
    ).then(
        fn=do_artist_search,
        inputs=[artist_search, artist_source_filter, artist_page_state],
        outputs=[artist_gallery, artist_results_state, artist_page_state, artist_total_pages_state, artist_page_indicator],
    )

    btn_artist_next.click(
        fn=lambda p, tp: min(tp, p + 1),
        inputs=[artist_page_state, artist_total_pages_state],
        outputs=[artist_page_state],
    ).then(
        fn=do_artist_search,
        inputs=[artist_search, artist_source_filter, artist_page_state],
        outputs=[artist_gallery, artist_results_state, artist_page_state, artist_total_pages_state, artist_page_indicator],
    )

    artist_page_jump.change(
        fn=lambda jp, tp: max(1, min(tp, int(jp or 1))),
        inputs=[artist_page_jump, artist_total_pages_state],
        outputs=[artist_page_state],
    ).then(
        fn=do_artist_search,
        inputs=[artist_search, artist_source_filter, artist_page_state],
        outputs=[artist_gallery, artist_results_state, artist_page_state, artist_total_pages_state, artist_page_indicator],
    )

    artist_gallery_click_idx.change(
        fn=on_artist_select,
        inputs=[artist_gallery_click_idx, artist_results_state],
        outputs=[artist_name_out, artist_tag_out, artist_preview, artist_status, artist_selected_id_state, btn_artist_favorite],
    )

    btn_artist_favorite.click(
        fn=toggle_artist_favorite,
        inputs=[artist_selected_id_state],
        outputs=[btn_artist_favorite],
    )

    # Add to txt2img — injects tag into the prompt textarea via JS
    btn_artist_add.click(
        fn=do_artist_add,
        inputs=[artist_tag_out],
        outputs=[artist_status],
        **get_js_kw("""(tag) => {
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (!promptEl || !tag) return [tag];
            const current = promptEl.value || '';
            const trimmed = current.trim();
            promptEl.value = trimmed ? (trimmed + ', ' + tag) : tag;
            promptEl.dispatchEvent(new Event('input', {bubbles: true}));
            promptEl.dispatchEvent(new Event('change', {bubbles: true}));
            return [tag];
        }""")
    )

    # Copy tag to clipboard
    btn_artist_copy.click(
        fn=do_artist_copy,
        inputs=[artist_tag_out],
        outputs=[artist_status],
        **get_js_kw("""(tag) => {
            if (!tag) return [tag];
            navigator.clipboard.writeText(tag).catch(() => {});
            return [tag];
        }""")
    )

    # Return all components for external integration if needed
    return {
        "gallery": artist_gallery,
        "search": artist_search,
        "source_filter": artist_source_filter,
        "btn_search": btn_artist_search,
        "page_state": artist_page_state,
        "total_pages_state": artist_total_pages_state,
        "results_state": artist_results_state,
    }


def build_artist_ui():
    """Build and return a complete Gradio Blocks for the Artists tab (top-level)."""
    with gr.Blocks(elem_id="sdcf_main_blocks") as blocks:
        build_artist_tab()
    return blocks
