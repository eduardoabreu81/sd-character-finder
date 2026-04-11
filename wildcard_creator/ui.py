"""
ui.py — Gradio UI for the YAML Wildcard Creator SD WebUI extension.

One tab:
  🎭 Characters → browse 20k Danbooru characters, search by name/tag/series,
                    send prompt tags directly to txt2img.

Entry points:
  build_ui()             – used by scripts/wildcard_creator.py (WebUI mode)
  build_standalone_ui()  – direct Gradio launch for local development
"""

from __future__ import annotations

import base64
import concurrent.futures
from collections import OrderedDict
import logging
import re
import html
from pathlib import Path

import gradio as gr
import requests

from wildcard_creator.character_db import get_character_db
from wildcard_creator.danbooru import DanbooruDB
from wildcard_creator.utils.strings import normalize_wildcard_name
from wildcard_creator.favorites import get_favorites_db
from wildcard_creator.search_history import get_search_history_db


_GR_VERSION = getattr(gr, "__version__", "3.0.0")

def get_js_kw(js_script: str) -> dict:
    """Helper to maintain compat with Gradio 3 (_js) and Gradio 4 (js)."""
    return {"js": js_script} if int(str(_GR_VERSION).split(".")[0]) >= 4 else {"_js": js_script}


def _get_default_danbooru_auth() -> tuple[str, str]:
    """Read Danbooru credentials from WebUI Settings when available."""
    try:
        from modules import shared  # type: ignore
        login = str(getattr(shared.opts, "sdcf_danbooru_login", "") or "")
        api_key = str(getattr(shared.opts, "sdcf_danbooru_api_key", "") or "")
        return login, api_key
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Tab -- Character Browser
# ---------------------------------------------------------------------------

def _build_characters_content():
    """Renders the character browser UI directly into the current Blocks context."""
    cdb = get_character_db()
    _populated = cdb.is_populated()
    _total = cdb.count() if _populated else 0
    _series_choices = ["All"] + [s for s, _ in cdb.list_series()] if _populated else ["All"]

    _NOT_POPULATED_MSG = (
        "⚠️ **Character database is downloading in the background!**\n\n"
        "It takes a few minutes to fetch the 20k characters for the first time. "
        "You can search, but results may be partial until it finishes."
    )

    if _total < 20000:
        gr.Markdown(_NOT_POPULATED_MSG)

    def _discover_wildcard_dirs() -> tuple[list[str], dict[str, str]]:
        """
        Discover wildcard folders using Forge/A1111 conventions:
          1) <webui_root>/scripts/wildcards
          2) <webui_root>/extensions/*/wildcards
          3) shared.opts.wildcard_dir (sd-dynamic-prompts)
        Falls back to local repo scan in standalone mode.
        """
        repo_root = Path(__file__).resolve().parent.parent
        labels: list[str] = []
        label_to_path: dict[str, str] = {}
        seen: set[str] = set()

        webui_root: Path | None = None

        def _label_for(path_obj: Path) -> str:
            try:
                if webui_root:
                    rel = path_obj.relative_to(webui_root)
                    return str(rel).replace("\\", "/")
            except Exception:
                pass
            return str(path_obj).replace("\\", "/")

        def _add_dir(path_like):
            if not path_like:
                return
            p = Path(path_like).expanduser()
            try:
                p = p.resolve()
            except Exception:
                pass
            key = str(p)
            if key in seen:
                return
            seen.add(key)
            label = _label_for(p)
            labels.append(label)
            label_to_path[label] = key

        try:
            from modules import shared  # type: ignore

            try:
                from modules import paths_internal as _paths_internal  # type: ignore
                script_path = getattr(_paths_internal, "script_path", "")
                if script_path:
                    webui_root = Path(script_path).resolve()
            except Exception:
                webui_root = None

            try:
                from modules import shared_paths as _shared_paths  # type: ignore

                # 1) Main scripts wildcard folder
                _add_dir(getattr(_shared_paths, "WILDCARD_PATH", None))

                # 2) Extension wildcard folders
                find_ext = getattr(_shared_paths, "find_ext_wildcard_paths", None)
                if callable(find_ext):
                    for ext_wc in find_ext():
                        _add_dir(ext_wc)
                else:
                    ext_path = getattr(_shared_paths, "EXT_PATH", None)
                    if ext_path:
                        for ext_wc in Path(ext_path).glob("*/wildcards"):
                            _add_dir(ext_wc)
            except Exception:
                # Fallback for environments without shared_paths helper
                try:
                    from modules import paths_internal as _paths_internal  # type: ignore
                    extensions_dir = getattr(_paths_internal, "extensions_dir", "")
                    if extensions_dir:
                        for ext_wc in Path(extensions_dir).glob("*/wildcards"):
                            _add_dir(ext_wc)
                    if webui_root:
                        _add_dir(webui_root / "scripts" / "wildcards")
                except Exception:
                    pass

            # 3) sd-dynamic-prompts custom wildcard_dir if configured
            custom_wildcard_dir = str(getattr(shared.opts, "wildcard_dir", "") or "").strip()
            if custom_wildcard_dir:
                _add_dir(custom_wildcard_dir)

        except Exception:
            # Standalone/local fallback
            for p in sorted(repo_root.rglob("wildcards")):
                if p.is_dir():
                    _add_dir(p)

        
        # Always ensure a local 'wildcards' folder exists inside the extension as a reliable fallback
        local_wc = repo_root / "wildcards"
        local_wc.mkdir(parents=True, exist_ok=True)
        _add_dir(local_wc)

        return labels, label_to_path

    _wildcard_dirs, _wildcard_dir_map = _discover_wildcard_dirs()

    gr.Markdown(
        f"### Browse {_total:,} Danbooru characters\n"
        "Search by name or tag, filter by series, then send to Generate."
    )

    def _load_favorites_initial() -> list[dict]:
        fav_ids: list[int] = []
        fav_file = Path(__file__).resolve().parent.parent / "data" / "favorites.json"
        try:
            if fav_file.exists():
                import json
                raw = json.loads(fav_file.read_text("utf-8"))
                if isinstance(raw, list):
                    fav_ids = [int(v) for v in raw if str(v).isdigit()]
        except Exception:
            fav_ids = []

        if not fav_ids:
            try:
                fav_ids = sorted(get_favorites_db().get_all())
            except Exception:
                fav_ids = []

        if not fav_ids:
            return []

        fav_list, _ = cdb.search("", favorites_list=fav_ids, limit=len(fav_ids))
        return fav_list

    def _render_initial_favorites_gallery(results_list: list[dict]) -> str:
        if not results_list:
            return "<div class='sdcf-char-gallery'><div class='civmodellist'><p style='color:#888;font-size:0.85em;padding:16px'>No characters to display.</p></div></div>"

        cards_html: list[str] = []
        for idx, item in enumerate(results_list):
            img_src = item.get("image_url") or "https://fakeimg.pl/400x400/282828/eae0d0/?text=No+Preview"
            name = item.get("name", "")
            source = item.get("source", "danbooru")

            safe_img = html.escape(str(img_src or ""), quote=True)
            safe_name = html.escape(str(name or ""))
            safe_source = html.escape(str(source or "danbooru"))
            onclick_js = (
                "const app=(window.gradioApp?window.gradioApp():document);"
                "const input=app.querySelector('#sdcf_fav_select_idx textarea, #sdcf_fav_select_idx input');"
                "if(!input){return false;}"
                f"input.value='{idx}';"
                "input.dispatchEvent(new Event('input',{bubbles:true}));"
                "input.dispatchEvent(new Event('change',{bubbles:true}));"
                "return false;"
            )
            safe_onclick = html.escape(onclick_js, quote=True)

            cards_html.append(
                f"""
                <button class='civmodelcard' onclick="{safe_onclick}">
                    <figure>
                        <div class='sdcf-badge sdcf-badge-favorite'>favorite</div>
                        <div class='sdcf-badge sdcf-badge-{safe_source}'>{safe_source}</div>
                        <img src='{safe_img}' alt='{safe_name}' loading='lazy' />
                        <figcaption>{safe_name}</figcaption>
                    </figure>
                </button>
                """
            )

        return "<div class='sdcf-char-gallery'><div class='civmodellist'>" + "".join(cards_html) + "</div></div>"

    _initial_favorites = _load_favorites_initial()
    _initial_favorites_df = [[r.get("name", ""), r.get("series", "") or "", r.get("source", "danbooru"), str(r.get("rank", ""))] for r in _initial_favorites]
    _initial_favorites_gallery = _render_initial_favorites_gallery(_initial_favorites)

    def _load_recent_initial() -> list[dict]:
        recent_file = Path(__file__).resolve().parent.parent / "data" / "recent_viewed.json"
        try:
            if recent_file.exists():
                import json
                raw = json.loads(recent_file.read_text("utf-8"))
                if isinstance(raw, list):
                    return [item for item in raw if isinstance(item, dict)]
        except Exception:
            pass
        return []

    def _render_initial_recent_gallery(results_list: list[dict]) -> str:
        if not results_list:
            return "<div class='sdcf-char-gallery'><div class='civmodellist'><p style='color:#888;font-size:0.85em;padding:16px'>No characters to display.</p></div></div>"

        cards_html: list[str] = []
        for idx, item in enumerate(results_list):
            img_src = item.get("image_url") or "https://fakeimg.pl/400x400/282828/eae0d0/?text=No+Preview"
            name = item.get("name", "")
            source = item.get("source", "danbooru")

            safe_img = html.escape(str(img_src or ""), quote=True)
            safe_name = html.escape(str(name or ""))
            safe_source = html.escape(str(source or "danbooru"))
            onclick_js = (
                "const app=(window.gradioApp?window.gradioApp():document);"
                "const input=app.querySelector('#sdcf_recent_select_idx textarea, #sdcf_recent_select_idx input');"
                "if(!input){return false;}"
                f"input.value='{idx}';"
                "input.dispatchEvent(new Event('input',{bubbles:true}));"
                "input.dispatchEvent(new Event('change',{bubbles:true}));"
                "return false;"
            )
            safe_onclick = html.escape(onclick_js, quote=True)

            cards_html.append(
                f"""
                <button class='civmodelcard' onclick="{safe_onclick}">
                    <figure>
                        <div class='sdcf-badge sdcf-badge-{safe_source}'>{safe_source}</div>
                        <img src='{safe_img}' alt='{safe_name}' loading='lazy' />
                        <figcaption>{safe_name}</figcaption>
                    </figure>
                </button>
                """
            )

        return "<div class='sdcf-char-gallery'><div class='civmodellist'>" + "".join(cards_html) + "</div></div>"

    _initial_recent = _load_recent_initial()
    _initial_recent_df = [[r.get("name", ""), r.get("series", "") or "", r.get("source", "danbooru"), str(r.get("rank", ""))] for r in _initial_recent]
    _initial_recent_gallery = _render_initial_recent_gallery(_initial_recent)

    with gr.Row():
        with gr.Column(scale=2):
            char_search = gr.Textbox(
                label="Search",
                placeholder="e.g. miku, saber, blue hair…",
                lines=1,
                elem_id="sdcf_char_search"
            )
        with gr.Column(scale=1):
            char_series = gr.Dropdown(
                label="Series",
                choices=_series_choices,
                value="All",
                interactive=True,
                elem_id="sdcf_char_series"
            )
        with gr.Column(scale=1):
            tag_status_filter = gr.Dropdown(
                label="Danbooru tag",
                choices=["All", "Missing Danbooru Tag", "Has Danbooru Tag"],
                value="All",
                interactive=True,
                elem_id="sdcf_tag_status_filter"
            )
        with gr.Column(scale=1, min_width=100):
            btn_char_search = gr.Button("🔍 Search", variant="primary", elem_id="sdcf_btn_search")
        with gr.Column(scale=1, min_width=100):
            btn_char_clear_search = gr.Button("✖ Clear Search", elem_id="sdcf_btn_clear_search")
        with gr.Column(scale=1, min_width=100):
            btn_char_reset = gr.Button("✖ Clear All", elem_id="sdcf_btn_clear_all")

    with gr.Row():
        source_filter = gr.Radio(
            label="Source",
            choices=["both", "danbooru", "e621"],
            value="both",
            interactive=True,
            elem_id="sdcf_source_filter"
        )
        favorites_only = gr.Checkbox(label="❤️ Favorites Only", value=False, interactive=True, elem_id="sdcf_favorites_only_chk")
        recent_searches = gr.Dropdown(
            label="Recent Searches",
            choices=get_search_history_db().get_all(),
            value=None,
            interactive=True,
            min_width=200,
            elem_id="sdcf_recent_searches"
        )

    current_page_state = gr.State(1)
    total_pages_state = gr.State(1)

    # Results Area
    with gr.Tabs():
        with gr.Tab("🔍 Search Results", id="tab_search"):
            with gr.Tabs():
                with gr.Tab("List View", id="tab_list"):
                    char_results = gr.Dataframe(
                        headers=["name", "series", "source", "rank"],
                        datatype=["str", "str", "str", "number"],
                        label="Results",
                        interactive=False,
                        wrap=False,
                        line_breaks=False,
                        height=600,
                        row_count=(30, "fixed"),
                    )
                with gr.Tab("Gallery View", id="tab_gallery"):
                    char_gallery = gr.HTML(
                        value="<div id='sdcf_char_gallery_html' class='sdcf-char-gallery'><div class='civmodellist'></div></div>",
                        label="Results",
                        elem_id="sdcf_char_gallery_html",
                    )
                    gallery_click_idx = gr.Textbox(value="-1", visible=False, elem_id="sdcf_gallery_click_idx")
            
            with gr.Row():
                with gr.Column(scale=4):
                    pass # spacer
                with gr.Column(scale=1, min_width=100):
                    btn_prev_page_bot = gr.Button("◀ Prev", interactive=True)
                with gr.Column(scale=1, min_width=120):
                    with gr.Row():
                        page_jump_bot = gr.Number(value=1, label="Page", precision=0, show_label=False, min_width=50)
                    page_indicator_bot = gr.Markdown("<div style='text-align: center; margin-top: 8px;'>Page 1 of 1</div>")
                with gr.Column(scale=1, min_width=100):
                    btn_next_page_bot = gr.Button("Next ▶", interactive=True)

        with gr.Tab("🕒 Recently Viewed", id="tab_recent"):
            recent_page_state = gr.State(1)
            with gr.Row():
                recent_save_session = gr.Checkbox(label="Save between sessions", value=True)
                btn_clear_recent = gr.Button("🗑️ Clear History", size="sm")
            with gr.Tabs():
                with gr.Tab("List View", id="tab_recent_list"):
                    recent_results_df = gr.Dataframe(
                        headers=["name", "series", "source", "rank"],
                        datatype=["str", "str", "str", "number"],
                        value=_initial_recent_df,
                        interactive=False,
                        wrap=False,
                        line_breaks=False,
                        height=600,
                        row_count=(30, "fixed"),
                    )
                with gr.Tab("Gallery View", id="tab_recent_gallery"):
                    recent_html = gr.HTML(value=_initial_recent_gallery)
            recent_select_idx = gr.Textbox(value="-1", visible=False, elem_id="sdcf_recent_select_idx")
            with gr.Row():
                with gr.Column(scale=4):
                    pass # spacer
                with gr.Column(scale=1, min_width=100):
                    btn_prev_recent = gr.Button("◀ Prev", interactive=True)
                with gr.Column(scale=1, min_width=120):
                    page_indicator_recent = gr.Markdown("<div style='text-align: center; margin-top: 8px;'>Page 1 of 1</div>")
                with gr.Column(scale=1, min_width=100):
                    btn_next_recent = gr.Button("Next ▶", interactive=True)

        with gr.Tab("❤️ Favorites", id="tab_favorites"):
            # Hidden trigger used for automatic initial load and internal refreshes.
            btn_refresh_favs = gr.Button("↻ Refresh Favorites", visible=True, elem_id="sdcf_fav_refresh_btn", elem_classes=["sdcf-hidden-trigger"])
            with gr.Tabs():
                with gr.Tab("List View", id="tab_fav_list"):
                    fav_results_df = gr.Dataframe(
                        headers=["name", "series", "source", "rank"],
                        datatype=["str", "str", "str", "number"],
                        value=_initial_favorites_df,
                        interactive=False,
                        wrap=False,
                        line_breaks=False,
                        height=600,
                        row_count=(30, "fixed"),
                    )
                with gr.Tab("Gallery View", id="tab_fav_gallery"):
                    fav_html = gr.HTML(value=_initial_favorites_gallery)
            fav_select_idx = gr.Textbox(value="-1", visible=False, elem_id="sdcf_fav_select_idx")

    char_results_state = gr.State([])  # full result list (with tags/image_url)
    recent_chars_state = gr.State(_initial_recent)   # list of {name, series, id, tags, danbooru_tag, image_url}
    fav_chars_state = gr.State(_initial_favorites)      # list for favorites

    gr.Markdown("---\n*Click a row above to load the character card.*")

    # Character card
    with gr.Row():
        with gr.Column(scale=2):
            char_name_out = gr.Textbox(label="Character", interactive=False, lines=1)
            char_series_out = gr.Textbox(label="Series", interactive=False, lines=1)
            char_danbooru_tag_out = gr.Textbox(
                label="Danbooru tag (canonical)",
                lines=1,
                interactive=True,
                placeholder="e.g. rosalina (mario)",
            )
            char_tags_out = gr.Textbox(label="Prompt tags", lines=4, interactive=True, elem_id="char_finder_tags_out")
            with gr.Row():
                btn_char_send = gr.Button("➡️ Send to Generate", variant="primary", size="lg")
                btn_char_add = gr.Button("➕ Add to txt2img", size="lg")
            with gr.Row():
                btn_char_copy = gr.Button("📋 Copy Tags", size="lg")
                btn_char_save_tag = gr.Button("💾 Save Danbooru Tag", size="lg")
                btn_favorite_toggle = gr.Button("🤍 Favorite", size="lg")
            char_selected_id = gr.State(None)
            char_send_status = gr.Textbox(visible=True, interactive=False, label="Status")

            with gr.Row():
                wildcard_name = gr.Textbox(
                    label="Wildcard name (.txt)",
                    placeholder="e.g. sakura_street_fighter",
                    lines=1,
                )
                wildcard_target_dir = gr.Dropdown(
                    label="Target wildcards folder",
                    choices=_wildcard_dirs,
                    value=_wildcard_dirs[0] if _wildcard_dirs else None,
                    interactive=len(_wildcard_dirs) > 1,
                    visible=len(_wildcard_dirs) > 1,
                )
                btn_export_wildcard_txt = gr.Button("💾 Save TXT wildcard")
            wildcard_dir_map_state = gr.State(_wildcard_dir_map)
        with gr.Column(scale=1, min_width=360):
            char_image = gr.HTML(
                value="<div class='sdcf-preview-empty'>No preview</div>",
                label="Preview",
                elem_id="sdcf_char_preview",
            )
            gr.Markdown("### Extra Tags (Danbooru)", elem_classes=["sdcf-small-header"])
            with gr.Row():
                btn_extra_fetch = gr.Button("⬇️ Fetch live tags", variant="secondary")
                btn_extra_apply = gr.Button("✅ Apply extras", variant="secondary")
            
            extra_tag_character = gr.CheckboxGroup(label="Character", choices=[], interactive=True, visible=False)
            extra_tag_copyright = gr.CheckboxGroup(label="Copyright/Series", choices=[], interactive=True, visible=False)
            extra_tag_general = gr.CheckboxGroup(label="General", choices=[], interactive=True, visible=False)
            extra_tag_artist = gr.CheckboxGroup(label="Artist", choices=[], interactive=True, visible=False)
            extra_tag_meta = gr.CheckboxGroup(label="Meta", choices=[], interactive=True, visible=False)
            extra_tags_meta = gr.State({})

    # ----- Events -----

    def get_shared_opt(key: str, default):
        try:
            from modules import shared
            if hasattr(shared, "opts") and hasattr(shared.opts, key):
                return getattr(shared.opts, key)
        except Exception:
            pass
        return default

    add_deduplicate_state = gr.State(bool(get_shared_opt("sdcf_add_deduplicate", True)))

    http_session = requests.Session()
    http_session.headers.update({"User-Agent": "SDCharacterFinder/1.0"})
    cover_data_uri_cache: OrderedDict[int, str] = OrderedDict()
    COVER_DATA_URI_CACHE_MAX = 500

    def _cache_get_data_uri(char_id: int) -> str | None:
        val = cover_data_uri_cache.get(char_id)
        if val is not None:
            cover_data_uri_cache.move_to_end(char_id)
        return val

    def _cache_set_data_uri(char_id: int, data_uri: str) -> None:
        cover_data_uri_cache[char_id] = data_uri
        cover_data_uri_cache.move_to_end(char_id)
        while len(cover_data_uri_cache) > COVER_DATA_URI_CACHE_MAX:
            cover_data_uri_cache.popitem(last=False)

    def do_search(query, series, tag_status, source, favorites_only, page, recent_chars, recent_page):
        query = (query or "").strip()
        series = (series or "All").strip() or "All"
        tag_status = (tag_status or "All").strip() or "All"
        source = (source or "both").strip() or "both"
        raw_limit = get_shared_opt("sdcf_search_limit", 30)
        raw_thumb_size = get_shared_opt("sdcf_gallery_thumb_size", 160)
        raw_gallery_columns = get_shared_opt("sdcf_gallery_columns", 5)
        try:
            limit = int(raw_limit)
        except Exception:
            limit = 30
        limit = max(1, min(limit, 30))
        try:
            thumb_size = int(raw_thumb_size)
        except Exception:
            thumb_size = 160
        thumb_size = max(100, min(thumb_size, 350))
        try:
            gallery_columns = int(raw_gallery_columns)
        except Exception:
            gallery_columns = 5
        gallery_columns = max(2, min(gallery_columns, 12))
        mobile_columns = min(gallery_columns, 3)
        
        try:
            favs = list(get_favorites_db().get_all()) if favorites_only else None
            offset = (page - 1) * limit
            results, total = cdb.search(
                query,
                series_filter=series if series != "All" else None,
                tag_status_filter=tag_status,
                source_filter=source,
                favorites_list=favs,
                limit=limit,
                offset=offset,
            )
            table = _render_list_df(results)
            gallery_html = _render_gallery_html(results, "sdcf_gallery_click_idx")
            
            total_pages = max(1, (total + limit - 1) // limit)
            page_text = f"<div style='text-align: center; margin-top: 8px;'>Page {page} of {total_pages} ({total} results)</div>"

            if query:
                get_search_history_db().add(query)

            # Auto-select the first result
            if results:
                card_outputs = _select_by_index(results, 0)
                updated_recents = _push_recent(results[0], recent_chars, True)
            else:
                card_outputs = _select_by_index([], 0)
                updated_recents = recent_chars

            recent_table, recent_gallery, recent_indicator, new_recent_page = _render_recent_page(updated_recents, recent_page)

            return (
                table,
                gr.update(value=gallery_html),
                results,
                page,
                total_pages,
                gr.update(value=page_text),
                page,
                page,
                gr.update(value=page_text),
                gr.update(choices=get_search_history_db().get_all()),
                *card_outputs,
                updated_recents,
                recent_table,
                recent_gallery,
                new_recent_page,
                gr.update(value=recent_indicator)
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                [],
                gr.update(value="<div id='sdcf_char_gallery_html'><div class='civmodellist'></div></div>"),
                [],
                1,
                1,
                gr.update(value="<div style='text-align: center; margin-top: 8px;'>Error</div>"),
                1,
                1,
                gr.update(value="<div style='text-align: center; margin-top: 8px;'>Error</div>"),
                gr.update(),
                "<div class='sdcf-preview-empty'>No preview</div>", "", "", "", "", None, "", "🤍 Favorite",
                recent_chars,
                _render_list_df(recent_chars[:30]),
                _render_gallery_html(recent_chars[:30], "sdcf_recent_select_idx"),
                recent_page,
                gr.update(value="<div style='text-align: center; margin-top: 8px;'>Error</div>")
            )

    def jump_page_action(query, series, tag_status, source, favorites_only, page, total_pages, recent_chars, recent_page):
        try:
            new_page = int(float(page))
        except Exception:
            new_page = 1
        new_page = max(1, min(total_pages, new_page))
        return do_search(query, series, tag_status, source, favorites_only, new_page, recent_chars, recent_page)

    def load_recent_search(recent_val, series, tag_status, source, favorites_only, recent_chars, recent_page):
        query = recent_val or ""
        res = do_search(query, series, tag_status, source, favorites_only, 1, recent_chars, recent_page)
        return (gr.update(value=query),) + res

    def search_first_page(query, series, tag_status, source, favorites_only, recent_chars, recent_page):
        return do_search(query, series, tag_status, source, favorites_only, 1, recent_chars, recent_page)

    def prev_page_action(query, series, tag_status, source, favorites_only, page, recent_chars, recent_page):
        new_page = max(1, page - 1)
        return do_search(query, series, tag_status, source, favorites_only, new_page, recent_chars, recent_page)

    def next_page_action(query, series, tag_status, source, favorites_only, page, total_pages, recent_chars, recent_page):
        new_page = min(total_pages, page + 1)
        return do_search(query, series, tag_status, source, favorites_only, new_page, recent_chars, recent_page)

    def do_clear_search():
        return (
            gr.update(value=""),
            gr.update(value="All"),
            gr.update(value="All"),
            gr.update(value="both"),
            gr.update(value=False),
            gr.update(value=None),
        )

    def do_reset_search():
        return (
            gr.update(value=""),          # char_search
            gr.update(value="All"),        # char_series
            gr.update(value="All"),        # tag_status_filter
            gr.update(value="both"),       # source_filter
            gr.update(value=False),        # favorites_only
            gr.update(value=[]),           # char_results
            gr.update(value="<div id='sdcf_char_gallery_html'><div class='civmodellist'></div></div>"),  # char_gallery
            [],                            # char_results_state
            1,                             # current_page_state
            1,                             # total_pages_state
            gr.update(value="<div style='text-align: center; margin-top: 8px;'>Page 1 of 1</div>"),  # page_indicator
            1,                             # page_jump_top
            1,                             # page_jump_bot
            gr.update(value="<div style='text-align: center; margin-top: 8px;'>Page 1 of 1</div>"),  # page_indicator_bot
            gr.update(value=None),         # recent_searches
            gr.update(value="<div class='sdcf-preview-empty'>No preview</div>"),  # char_image
            gr.update(value=""),           # char_name_out
            gr.update(value=""),           # char_series_out
            gr.update(value=""),           # char_danbooru_tag_out
            gr.update(value=""),           # char_tags_out
            None,                          # char_selected_id
            gr.update(value="🤍 Favorite"), # btn_favorite_toggle
            gr.update(value=""),           # char_send_status
            gr.update(value=""),           # wildcard_name
            gr.update(choices=[], value=[], visible=False),  # extra_tag_character
            gr.update(choices=[], value=[], visible=False),  # extra_tag_copyright
            gr.update(choices=[], value=[], visible=False),  # extra_tag_general
            gr.update(choices=[], value=[], visible=False),  # extra_tag_artist
            gr.update(choices=[], value=[], visible=False),  # extra_tag_meta
            {},                            # extra_tags_meta
        )

    def _render_list_df(results_list: list) -> list:
        return [[r.get("name", ""), r.get("series", "") or "", r.get("source", "danbooru"), str(r.get("rank", ""))] for r in results_list]

    def _render_recent_page(recent_chars, page):
        limit = get_shared_opt("sdcf_search_limit", 30)
        try: limit = int(limit)
        except Exception: limit = 30
        limit = max(1, min(limit, 30))
        
        total = len(recent_chars)
        total_pages = max(1, (total + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        
        offset = (page - 1) * limit
        page_data = recent_chars[offset:offset+limit]
        
        table = _render_list_df(page_data)
        gallery = _render_gallery_html(page_data, "sdcf_recent_select_idx", global_offset=offset)
        
        indicator = f"<div style='text-align: center; margin-top: 8px;'>Page {page} of {total_pages}</div>"
        return table, gallery, indicator, page

    def _render_gallery_html(results_list: list, target_idx_elem_id="sdcf_gallery_click_idx", global_offset=0) -> str:
        if not results_list:
            return "<div class='sdcf-char-gallery'><div class='civmodellist'><p style='color:#888;font-size:0.85em;padding:16px'>No characters to display.</p></div></div>"

        raw_thumb_size = get_shared_opt("sdcf_gallery_thumb_size", 160)
        raw_gallery_columns = get_shared_opt("sdcf_gallery_columns", 5)
        try: thumb_size = int(raw_thumb_size)
        except Exception: thumb_size = 160
        thumb_size = max(100, min(thumb_size, 350))
        
        try: gallery_columns = int(raw_gallery_columns)
        except Exception: gallery_columns = 5
        gallery_columns = max(2, min(gallery_columns, 12))
        mobile_columns = min(gallery_columns, 3)

        repo_root = Path(__file__).resolve().parent.parent
        covers_dir = repo_root / "data" / "covers"
        covers_dir.mkdir(parents=True, exist_ok=True)
        
        def fetch_one(r):
            url = r.get("image_url")
            char_id = r.get("id")
            name = r.get("name", "")
            src_val = r.get("source", "danbooru")
            if not url or not char_id:
                return ("https://fakeimg.pl/400x400/282828/eae0d0/?text=No+Preview", name, src_val)

            cached_data_uri = _cache_get_data_uri(int(char_id))
            if cached_data_uri:
                return (cached_data_uri, name, src_val)
            
            cov_path = covers_dir / f"{char_id}.jpg"
            if not cov_path.exists():
                try:
                    resp = http_session.get(url, timeout=3)
                    if resp.status_code == 200:
                        cov_path.write_bytes(resp.content)
                except Exception:
                    pass
            
            if cov_path.exists():
                try:
                    img_b64 = base64.b64encode(cov_path.read_bytes()).decode("ascii")
                    data_uri = f"data:image/jpeg;base64,{img_b64}"
                    _cache_set_data_uri(int(char_id), data_uri)
                    return (data_uri, name, src_val)
                except Exception:
                    return (url, name, src_val)
            return (url, name, src_val)

        gallery = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(results_list))) as executor:
            gallery = list(executor.map(fetch_one, results_list))

        cards_html: list[str] = []
        try: fav_set = get_favorites_db().get_all()
        except Exception: fav_set = set()

        for idx, (img_src, name, source) in enumerate(gallery):
            char_id = results_list[idx].get("id")
            fav_html = "<div class='sdcf-badge sdcf-badge-favorite'>favorite</div>" if char_id and int(char_id) in fav_set else ""
            
            safe_img = html.escape(str(img_src or ""), quote=True)
            safe_name = html.escape(str(name or ""))
            global_idx = global_offset + idx
            onclick_js = (
                "const app=(window.gradioApp?window.gradioApp():document);"
                f"const input=app.querySelector('#{target_idx_elem_id} textarea, #{target_idx_elem_id} input');"
                "if(!input){return false;}"
                f"input.value='{global_idx}';"
                "input.dispatchEvent(new Event('input',{bubbles:true}));"
                "input.dispatchEvent(new Event('change',{bubbles:true}));"
                "return false;"
            )
            safe_onclick = html.escape(onclick_js, quote=True)
            cards_html.append(
                f"""
                <button class='civmodelcard' onclick="{safe_onclick}">
                    <figure>
                        {fav_html}
                        <div class='sdcf-badge sdcf-badge-{source}'>{source}</div>
                        <img src='{safe_img}' alt='{safe_name}' loading='lazy' />
                        <figcaption>{safe_name}</figcaption>
                    </figure>
                </button>
                """
            )

        return (
            f"<div id='{target_idx_elem_id}_html' class='sdcf-char-gallery' style='--sdcf-gallery-cols:{gallery_columns};--sdcf-mobile-cols:{mobile_columns};--sdcf-thumb-size:{thumb_size}px'><div class='civmodellist'>"
            + "".join(cards_html)
            + "</div></div>"
        )

    def _build_preview_html(src: str | None, title: str, is_favorite: bool = False, source: str = "danbooru") -> str:
        if not src:
            return "<div class='sdcf-preview-empty'>No preview</div>"

        safe_src = html.escape(src, quote=True)
        safe_title = html.escape(title or "Preview")
        source_value = (source or "danbooru").strip().lower()
        if source_value not in {"danbooru", "e621"}:
            source_value = "danbooru"
        safe_source = html.escape(source_value)
        fav_preview_badge = "<div class='sdcf-badge sdcf-badge-favorite sdcf-preview-favorite'>favorite</div>" if is_favorite else ""
        src_preview_badge = f"<div class='sdcf-badge sdcf-badge-{safe_source} sdcf-preview-source'>{safe_source}</div>"
        return f"""
<div class='sdcf-preview-wrap'>
    {fav_preview_badge}
    {src_preview_badge}
    <div class='sdcf-preview-hint'>Click to expand</div>
    <img
        src='{safe_src}'
        alt='{safe_title}'
        class='sdcf-preview-image'
        onclick="const m=document.getElementById('sdcf-preview-modal');const i=document.getElementById('sdcf-preview-modal-img');if(m&&i){{i.src=this.src;m.style.display='flex';}}"
    />
<div id='sdcf-preview-modal' class='sdcf-preview-modal' onclick="if(event.target===this){{this.style.display='none';}}">
    <button class='sdcf-preview-close' onclick="document.getElementById('sdcf-preview-modal').style.display='none';return false;">✕</button>
    <img id='sdcf-preview-modal-img' alt='Expanded preview' class='sdcf-preview-modal-img' />
</div>
</div>
"""

    def _favorite_button_label(char_id) -> str:
        try:
            if char_id and get_favorites_db().is_favorite(int(char_id)):
                return "💔 Unfavorite"
        except Exception:
            pass
        return "🤍 Favorite"

    def _select_by_index(results_state, row_idx):
        if not results_state or row_idx < 0 or row_idx >= len(results_state):
            return "<div class='sdcf-preview-empty'>No preview</div>", "", "", "", "", None, "", "🤍 Favorite"
        char = results_state[row_idx]
        canonical_tag = (char.get("danbooru_tag") or "").strip()
        # DB tags are mandatory — always use them as the prompt base.
        # canonical_tag is only a fallback when tags is empty.
        prompt_value = (char.get("tags") or canonical_tag or "").strip()
        
        img_url = char.get("image_url")
        char_id = char.get("id")
        image_value = None
        if img_url:
            image_value = img_url
            if char_id:
                try:
                    import base64
                    repo_root = Path(__file__).resolve().parent.parent
                    covers_dir = repo_root / "data" / "covers"
                    cov_path = covers_dir / f"{char_id}.jpg"
                    if cov_path.exists():
                        image_value = f"data:image/jpeg;base64,{base64.b64encode(cov_path.read_bytes()).decode('ascii')}"
                except Exception:
                    pass

        is_favorite = False
        try:
            if char_id:
                is_favorite = get_favorites_db().is_favorite(int(char_id))
        except Exception:
            is_favorite = False

        preview_html = _build_preview_html(
            image_value,
            char.get("name") or "Preview",
            is_favorite=is_favorite,
            source=char.get("source", "danbooru"),
        )


        return (
            preview_html,
            char["name"],
            char.get("series") or "",
            canonical_tag,
            prompt_value,
            char.get("id"),
            _normalize_wildcard_name(char["name"]),
            _favorite_button_label(char.get("id")),
        )

    # --- Recently viewed helpers ---

    def _save_recent_history(recents, do_save):
        if not do_save:
            return
        try:
            import json
            recent_file = Path(__file__).resolve().parent.parent / "data" / "recent_viewed.json"
            recent_file.parent.mkdir(parents=True, exist_ok=True)
            recent_file.write_text(json.dumps(recents), "utf-8")
        except Exception:
            pass

    def _push_recent(char: dict, current_recents: list, do_save: bool = True) -> list:
        """Prepend char to recent list, deduplicate by id, keep last 100."""
        char_id = char.get("id")
        updated = [c for c in current_recents if c.get("id") != char_id]
        updated.insert(0, {
            "id": char_id,
            "name": char.get("name", ""),
            "series": char.get("series") or "",
            "tags": char.get("tags") or "",
            "danbooru_tag": char.get("danbooru_tag") or "",
            "image_url": char.get("image_url") or "",
            "source": char.get("source", "danbooru"),
        })
        final_list = updated[:100]
        _save_recent_history(final_list, do_save)
        return final_list

    def on_row_select(results_state, recent_chars, do_save, recent_page, evt: gr.SelectData):
        row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        card_outputs = _select_by_index(results_state, row_idx)
        if results_state and 0 <= row_idx < len(results_state):
            updated_recents = _push_recent(results_state[row_idx], recent_chars, do_save)
        else:
            updated_recents = recent_chars
        
        t, g, i, p = _render_recent_page(updated_recents, recent_page)
        return (*card_outputs, updated_recents, t, g, p, gr.update(value=i))

    def on_gallery_click(idx_text, results_state, recent_chars, do_save, recent_page):
        try:
            row_idx = int(float(idx_text))
        except Exception:
            row_idx = -1
        card_outputs = _select_by_index(results_state, row_idx)
        if results_state and 0 <= row_idx < len(results_state):
            updated_recents = _push_recent(results_state[row_idx], recent_chars, do_save)
        else:
            updated_recents = recent_chars
        
        t, g, i, p = _render_recent_page(updated_recents, recent_page)
        return (*card_outputs, updated_recents, t, g, p, gr.update(value=i))

    def on_recent_click(idx_text, recent_chars, do_save, recent_page):
        """Select a character from the recently viewed panel."""
        try:
            row_idx = int(float(idx_text))
        except Exception:
            row_idx = -1
        card_outputs = _select_by_index(recent_chars, row_idx)
        # Re-push to front when re-selected
        if recent_chars and 0 <= row_idx < len(recent_chars):
            updated_recents = _push_recent(recent_chars[row_idx], recent_chars, do_save)
        else:
            updated_recents = recent_chars
            
        t, g, i, p = _render_recent_page(updated_recents, recent_page)
        return (*card_outputs, updated_recents, t, g, p, gr.update(value=i))


    def save_manual_danbooru_tag(selected_id, manual_tag):
        if not selected_id:
            return gr.update(value="⚠️ Select a character first"), gr.update()
        manual_tag = (manual_tag or "").strip()
        if not manual_tag:
            return gr.update(value="⚠️ Enter a Danbooru tag first"), gr.update()
        ok = cdb.save_danbooru_tag(int(selected_id), manual_tag)
        if not ok:
            return gr.update(value="❌ Failed to save Danbooru tag"), gr.update()
        return gr.update(value="✅ Danbooru tag saved"), gr.update(value=manual_tag)

    def _normalize_wildcard_name(name: str) -> str:
        name = (name or "").strip().replace(" ", "_").lower()
        name = re.sub(r"[^a-z0-9_\-]", "", name)
        return name[:50]

    def _order_tags_novelai_like(tags: list[str], category_map: dict[str, int]) -> list[str]:
        # Inspired by Takenoko's ordering concept, implemented from scratch.
        count_re = re.compile(r"^[1-6]\+?(girl|boy)s?$", re.IGNORECASE)
        boys: list[str] = []
        girls: list[str] = []
        characters: list[str] = []
        series: list[str] = []
        others: list[str] = []

        for tag in tags:
            t = (tag or "").strip()
            if not t:
                continue
            lower_t = t.lower().replace("_", " ")
            if count_re.match(lower_t):
                if "girl" in lower_t:
                    girls.append(t)
                else:
                    boys.append(t)
                continue

            cat = category_map.get(lower_t)
            if cat == 4:
                characters.append(t)
            elif cat == 3:
                series.append(t)
            else:
                others.append(t)

        return boys + girls + characters + series + others

    def do_add_to_generate(tags, deduplicate_enabled):
        if not tags:
            return gr.update(value="⚠️ No tags to add")
        if deduplicate_enabled:
            return gr.update(value="✅ Added to txt2img (dedupe on)")
        return gr.update(value="✅ Added to txt2img")

    def do_export_wildcard_txt(name: str, tags: str, target_dir: str, dir_map: dict[str, str]):
        safe = _normalize_wildcard_name(name)
        if not safe:
            return gr.update(value="⚠️ Enter a valid wildcard name")
        if not tags or not tags.strip():
            return gr.update(value="⚠️ No tags to export")
        if not target_dir:
            return gr.update(value="⚠️ Select a target wildcards folder")
        try:
            selected = (dir_map or {}).get(target_dir, "")
            if not selected:
                return gr.update(value="❌ Invalid target folder")
            target_path = Path(selected).resolve()
            target_path.mkdir(parents=True, exist_ok=True)
            out_file = target_path / f"{safe}.txt"
            out_file.write_text(tags.strip() + "\n", encoding="utf-8")
            out_str = str(out_file).replace("\\", "/")
            return gr.update(value=f"✅ Saved {out_str} — use __{safe}__ in prompt")
        except Exception as exc:
            return gr.update(value=f"❌ Failed to save wildcard: {exc}")

    def do_send_to_generate(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to send")
        return gr.update(value="✅ Sent to txt2img")

    def do_copy_tags(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to copy")
        return gr.update(value="✅ Copied to clipboard")

    btn_char_search.click(
        search_first_page,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
        **get_js_kw("""(query, series, tag_status, source, favorites_only, recent_chars, recent_page) => {
            const normalized = (value) => (value || '').toLowerCase().replace(/\s+/g, '');
            const targetKey = normalized('search results');
            const app = (window.gradioApp ? window.gradioApp() : document);
            const candidates = app.querySelectorAll('button, [role="tab"]');
            for (const candidate of candidates) {
                const text = normalized(candidate.textContent);
                const id = normalized(candidate.id || '');
                const controls = normalized(candidate.getAttribute('aria-controls') || '');
                if (text === targetKey || id.includes('tab_search') || controls.includes('tab_search')) {
                    candidate.click();
                    break;
                }
            }
            return [query, series, tag_status, source, favorites_only, recent_chars, recent_page];
        }""")
    )
    recent_searches.change(
        load_recent_search,
        inputs=[recent_searches, char_series, tag_status_filter, source_filter, favorites_only, recent_chars_state, recent_page_state],
        outputs=[char_search, char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    char_search.submit(
        search_first_page,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    btn_prev_page.click(
        prev_page_action,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, current_page_state, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    btn_next_page.click(
        next_page_action,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, current_page_state, total_pages_state, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    btn_prev_page_bot.click(
        prev_page_action,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, current_page_state, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    btn_next_page_bot.click(
        next_page_action,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, current_page_state, total_pages_state, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    page_jump_top.submit(
        jump_page_action,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, page_jump_top, total_pages_state, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    page_jump_bot.submit(
        jump_page_action,
        inputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, page_jump_bot, total_pages_state, recent_chars_state, recent_page_state],
        outputs=[char_results, char_gallery, char_results_state, current_page_state, total_pages_state, page_indicator, page_jump_top, page_jump_bot, page_indicator_bot, recent_searches, char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, char_send_status, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    btn_char_clear_search.click(
        do_clear_search,
        outputs=[char_search, char_series, tag_status_filter, source_filter, favorites_only, recent_searches],
    )
    char_results.select(
        on_row_select,
        inputs=[char_results_state, recent_chars_state, recent_save_session, recent_page_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, wildcard_name, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    gallery_click_idx.change(
        on_gallery_click,
        inputs=[gallery_click_idx, char_results_state, recent_chars_state, recent_save_session, recent_page_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, wildcard_name, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    recent_select_idx.change(
        on_recent_click,
        inputs=[recent_select_idx, recent_chars_state, recent_save_session, recent_page_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, wildcard_name, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )

    def clear_recent_viewed():
        empty = []
        try:
            recent_file = Path(__file__).resolve().parent.parent / "data" / "recent_viewed.json"
            if recent_file.exists():
                recent_file.unlink()
        except:
            pass
        t, g, i, p = _render_recent_page(empty, 1)
        return empty, t, g, p, gr.update(value=i)

    btn_clear_recent.click(
        clear_recent_viewed,
        outputs=[recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent]
    )

    def prev_recent_action(recent_chars, page):
        new_page = max(1, page - 1)
        t, g, i, p = _render_recent_page(recent_chars, new_page)
        return t, g, p, gr.update(value=i)

    def next_recent_action(recent_chars, page):
        new_page = page + 1
        t, g, i, p = _render_recent_page(recent_chars, new_page)
        return t, g, p, gr.update(value=i)

    btn_prev_recent.click(
        prev_recent_action,
        inputs=[recent_chars_state, recent_page_state],
        outputs=[recent_results_df, recent_html, recent_page_state, page_indicator_recent]
    )

    btn_next_recent.click(
        next_recent_action,
        inputs=[recent_chars_state, recent_page_state],
        outputs=[recent_results_df, recent_html, recent_page_state, page_indicator_recent]
    )

    def do_refresh_favs():
        fav_ids: list[int] = []
        fav_file = Path(__file__).resolve().parent.parent / "data" / "favorites.json"
        try:
            if fav_file.exists():
                import json
                raw = json.loads(fav_file.read_text("utf-8"))
                if isinstance(raw, list):
                    fav_ids = [int(v) for v in raw if str(v).isdigit()]
        except Exception:
            fav_ids = []

        # Fallback to in-memory helper in case file read fails unexpectedly.
        if not fav_ids:
            try:
                from wildcard_creator.favorites import get_favorites_db
                fav_ids = sorted(get_favorites_db().get_all())
            except Exception:
                fav_ids = []

        if not fav_ids:
            empty = []
            return empty, _render_list_df(empty), _render_gallery_html(empty, "sdcf_fav_select_idx")

        # Load the favorite characters from DB using search with favorites_list filter
        fav_list, _ = cdb.search("", favorites_list=fav_ids, limit=len(fav_ids))
        return fav_list, _render_list_df(fav_list), _render_gallery_html(fav_list, "sdcf_fav_select_idx")

    btn_refresh_favs.click(
        do_refresh_favs,
        outputs=[fav_chars_state, fav_results_df, fav_html]
    )

    fav_results_df.select(
        on_row_select,
        inputs=[fav_chars_state, recent_chars_state, recent_save_session, recent_page_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, wildcard_name, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )
    fav_select_idx.change(
        on_gallery_click,
        inputs=[fav_select_idx, fav_chars_state, recent_chars_state, recent_save_session, recent_page_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id, wildcard_name, btn_favorite_toggle, recent_chars_state, recent_results_df, recent_html, recent_page_state, page_indicator_recent],
    )

    btn_char_save_tag.click(
        save_manual_danbooru_tag,
        inputs=[char_selected_id, char_danbooru_tag_out],
        outputs=[char_send_status, char_tags_out],
        **get_js_kw("""(id, tag) => {
            if(!confirm('Save to database? This will become the default tag for this character.')) {
                throw new Error('Cancelled by user');
            }
            return [id, tag];
        }""")
    )

    def _find_char_by_id_in_states(char_id, *states):
        for state in states:
            if not state:
                continue
            for item in state:
                try:
                    if int(item.get("id")) == int(char_id):
                        return item
                except Exception:
                    continue
        return None

    def toggle_favorite(char_id, search_state, recent_state, fav_state):
        if not char_id:
            return gr.update(value="⚠️ Select a character first"), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        try:
            from wildcard_creator.favorites import get_favorites_db
            db = get_favorites_db()
            is_fav = db.toggle(int(char_id))

            selected = _find_char_by_id_in_states(char_id, search_state, recent_state, fav_state)
            preview_html = gr.update()
            if selected:
                preview_html = gr.update(
                    value=_build_preview_html(
                        selected.get("image_url"),
                        selected.get("name") or "Preview",
                        is_favorite=is_fav,
                        source=selected.get("source", "danbooru"),
                    )
                )

            updated_fav_state, updated_fav_df, updated_fav_html = do_refresh_favs()

            if is_fav:
                return (
                    gr.update(value="✅ Added to favorites"),
                    preview_html,
                    gr.update(value="💔 Unfavorite"),
                    updated_fav_state,
                    updated_fav_df,
                    updated_fav_html,
                )
            else:
                return (
                    gr.update(value="✅ Removed from favorites"),
                    preview_html,
                    gr.update(value="🤍 Favorite"),
                    updated_fav_state,
                    updated_fav_df,
                    updated_fav_html,
                )
        except Exception as e:
            return gr.update(value=f"❌ Failed to toggle favorite: {e}"), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    btn_favorite_toggle.click(
        toggle_favorite,
        inputs=[char_selected_id, char_results_state, recent_chars_state, fav_chars_state],
        outputs=[char_send_status, char_image, btn_favorite_toggle, fav_chars_state, fav_results_df, fav_html],
    )
    btn_char_send.click(
        fn=do_send_to_generate,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        **get_js_kw("""(tags) => {
            const switchToTab = (target) => {
                const normalized = (value) => (value || '').toLowerCase().replace(/\s+/g, '');
                const targetKey = normalized(target);
                const app = gradioApp();
                const candidates = app.querySelectorAll('button, [role="tab"]');
                for (const candidate of candidates) {
                    const text = normalized(candidate.textContent);
                    const id = normalized(candidate.id || '');
                    const controls = normalized(candidate.getAttribute('aria-controls') || '');
                    if (text === targetKey || id.includes(targetKey) || controls.includes(targetKey)) {
                        candidate.click();
                        return;
                    }
                }
            };
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (promptEl && tags) {
                promptEl.value = tags;
                promptEl.dispatchEvent(new Event('input', {bubbles: true}));
                promptEl.dispatchEvent(new Event('change', {bubbles: true}));
                switchToTab('txt2img');
            }
            return [tags];
        }""")
    )
    btn_char_add.click(
        fn=do_add_to_generate,
        inputs=[char_tags_out, add_deduplicate_state],
        outputs=[char_send_status],
        **get_js_kw("""(tags, deduplicateEnabled) => {
            const switchToTab = (target) => {
                const normalized = (value) => (value || '').toLowerCase().replace(/\s+/g, '');
                const targetKey = normalized(target);
                const app = gradioApp();
                const candidates = app.querySelectorAll('button, [role="tab"]');
                for (const candidate of candidates) {
                    const text = normalized(candidate.textContent);
                    const id = normalized(candidate.id || '');
                    const controls = normalized(candidate.getAttribute('aria-controls') || '');
                    if (text === targetKey || id.includes(targetKey) || controls.includes(targetKey)) {
                        candidate.click();
                        return;
                    }
                }
            };
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (!promptEl || !tags) return [tags];

            const dedupeOn = !(deduplicateEnabled === false || deduplicateEnabled === 'false' || deduplicateEnabled === 0 || deduplicateEnabled === '0');

            if (!dedupeOn) {
                const current = (promptEl.value || '').trim();
                promptEl.value = current ? `${current}, ${tags}` : tags;
                promptEl.dispatchEvent(new Event('input', {bubbles: true}));
                promptEl.dispatchEvent(new Event('change', {bubbles: true}));
                switchToTab('txt2img');
                return [tags];
            }

            const parse = (s) => (s || '').split(',').map(x => x.trim()).filter(Boolean);
            const norm = (s) => (s || '').toLowerCase().replace(/_/g, ' ');
            const existing = parse(promptEl.value);
            const incoming = parse(tags);
            const seen = new Set(existing.map(norm));
            for (const tag of incoming) {
                const k = norm(tag);
                if (!seen.has(k)) {
                    existing.push(tag);
                    seen.add(k);
                }
            }

            promptEl.value = existing.join(', ');
            promptEl.dispatchEvent(new Event('input', {bubbles: true}));
            promptEl.dispatchEvent(new Event('change', {bubbles: true}));
            switchToTab('txt2img');
            return [tags];
        }""")
    )
    btn_char_copy.click(
        fn=do_copy_tags,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        **get_js_kw("""(tags) => {
            if (!tags) return [tags];
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(tags);
            } else {
                const ta = document.createElement('textarea');
                ta.value = tags;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            return [tags];
        }""")
    )
    btn_export_wildcard_txt.click(
        fn=do_export_wildcard_txt,
        inputs=[wildcard_name, char_tags_out, wildcard_target_dir, wildcard_dir_map_state],
        outputs=[char_send_status],
    )

    # =========================================================
    # Extra tags (discrete mode)

        
    _live_db = DanbooruDB()

    def _fetch_extra_tags(selected_name, selected_series, manual_danbooru_tag, current_prompt):
        def _empty():
            return (
                gr.update(choices=[], value=[], visible=False),
                gr.update(choices=[], value=[], visible=False),
                gr.update(choices=[], value=[], visible=False),
                gr.update(choices=[], value=[], visible=False),
                gr.update(choices=[], value=[], visible=False),
                {},
            )
            
        seed = (manual_danbooru_tag or selected_name or "").strip()
        if not seed:
            yield (*_empty(), gr.update(value="⚠️ Select a character first"))
            return

        yield (*_empty(), gr.update(value="⏳ Fetching live tags from Danbooru..."))

        login, api_key = _get_default_danbooru_auth()
        n_posts = get_shared_opt("sdcf_live_n_posts", 120)
        top_n = get_shared_opt("sdcf_live_top_n", 60)
        min_freq = get_shared_opt("sdcf_live_min_freq", 0.08)
        
        try:
            tags = _live_db.fetch_character_post_tags(
                seed, login=login, api_key=api_key, n_posts=n_posts, top_n=top_n, min_freq=min_freq
            )
        except Exception as exc:
            yield (*_empty(), gr.update(value=f"❌ {exc}"))
            return
            
        category_map: dict[str, int] = {}
        
        def _norm(tag_str):
            if not tag_str: return ""
            return tag_str.strip().lower().replace("_", " ")

        import re as re_mod
        existing_tags = set(re_mod.split(r",\s*", (current_prompt or "").strip().lower()))

        cat_lists = {4: [], 3: [], 0: [], 1: [], 5: []}
        
        for t in tags:
            try:
                name_val = t.name if hasattr(t, 'name') else t.get("tag", "") if isinstance(t, dict) else str(t)
                cat_val = t.category if hasattr(t, 'category') else t.get("category", 0) if isinstance(t, dict) else 0
            except:
                continue
                
            name_clean = _norm(name_val)
            if not name_clean or name_clean in existing_tags: continue
            
            cat_val = int(cat_val)
            if cat_val not in cat_lists: cat_val = 0
            
            cat_lists[cat_val].append(name_val)
            category_map[name_clean] = cat_val

        # Ensure seed and series
        seed_norm = _norm(seed)
        if seed and seed_norm not in category_map and seed_norm not in existing_tags:
            cat_lists[4].insert(0, seed)
            category_map[seed_norm] = 4
            
        series_norm = _norm(selected_series)
        if selected_series and series_norm not in category_map and series_norm not in existing_tags:
            cat_lists[3].insert(0, selected_series)
            category_map[series_norm] = 3

        def _dedup(items):
            seen = set()
            res = []
            for tag in items:
                k = _norm(tag)
                if k not in seen:
                    seen.add(k)
                    res.append(tag)
            return res
            
        c4 = _dedup(cat_lists[4])
        c3 = _dedup(cat_lists[3])
        c0 = _dedup(cat_lists[0])
        c1 = _dedup(cat_lists[1])
        c5 = _dedup(cat_lists[5])

        def _mk(lst):
            return gr.update(choices=lst, value=[], visible=len(lst) > 0)
            
        total = len(c4)+len(c3)+len(c0)+len(c1)+len(c5)

        yield (_mk(c4), _mk(c3), _mk(c0), _mk(c1), _mk(c5), category_map, gr.update(value=f"✅ Fetched {total} tags"))

    def _apply_extra_tags(current_prompt, c4, c3, c0, c1, c5, category_map):
        c4 = list(c4 or [])
        c3 = list(c3 or [])
        c0 = list(c0 or [])
        c1 = list(c1 or [])
        c5 = list(c5 or [])
        
        selected_extras = c4 + c3 + c0 + c1 + c5

        if not selected_extras:
            return gr.update(), gr.update(value="⚠️ Select at least one extra tag")

        current_parts = [p.strip() for p in (current_prompt or "").split(",") if p.strip()]

        def _norm(tag_str):
            return tag_str.strip().lower().replace("_", " ")

        seen = {_norm(p) for p in current_parts}
        added = []
        for tag in selected_extras:
            norm_tag = _norm(tag)
            if norm_tag not in seen:
                current_parts.append(tag)
                seen.add(norm_tag)
                added.append(tag)

        ordered = _order_tags_novelai_like(current_parts, category_map or {})

        if not added:
            return gr.update(value=", ".join(ordered)), gr.update(value="ℹ️ All selected tags were already present")

        return (
            gr.update(value=", ".join(ordered)),
            gr.update(value=f"✅ Added {len(added)} extra tag(s)"),
        )

    btn_char_reset.click(
        do_reset_search,
        outputs=[
            char_search,
            char_series,
            tag_status_filter,
            source_filter,
            favorites_only,
            char_results,
            char_gallery,
            char_results_state,
            current_page_state,
            total_pages_state,
            page_indicator,
            page_jump_top,
            page_jump_bot,
            page_indicator_bot,
            recent_searches,
            char_image,
            char_name_out,
            char_series_out,
            char_danbooru_tag_out,
            char_tags_out,
            char_selected_id,
            btn_favorite_toggle,
            char_send_status,
            wildcard_name,
            extra_tag_character,
            extra_tag_copyright,
            extra_tag_general,
            extra_tag_artist,
            extra_tag_meta,
            extra_tags_meta,
        ],
    )

    btn_extra_fetch.click(
        _fetch_extra_tags,
        inputs=[char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out],
        outputs=[
            extra_tag_character,
            extra_tag_copyright,
            extra_tag_general,
            extra_tag_artist,
            extra_tag_meta,
            extra_tags_meta,
            char_send_status
        ],
    )

    btn_extra_apply.click(
        _apply_extra_tags,
        inputs=[
            char_tags_out, 
            extra_tag_character,
            extra_tag_copyright,
            extra_tag_general,
            extra_tag_artist,
            extra_tag_meta,
            extra_tags_meta
        ],
        outputs=[char_tags_out, char_send_status],
    )

    gr.HTML('<button class="sdcf-jump-top" onclick="window.scrollTo({top: 0, behavior: \'smooth\'})" title="Jump to Top">⬆</button>')
    gr.HTML(
        """
<script>
(() => {
    const clickAutoFavoritesRefresh = () => {
        const app = (window.gradioApp ? window.gradioApp() : document);
        const btn = app.querySelector('#sdcf_fav_refresh_btn button, #sdcf_fav_refresh_btn');
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    };

    let tries = 0;
    const maxTries = 20;
    const timer = setInterval(() => {
        tries += 1;
        if (clickAutoFavoritesRefresh() || tries >= maxTries) {
            clearInterval(timer);
        }
    }, 200);
})();
</script>
        """
    )

# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    """
    Build the full Gradio UI (attach to SD WebUI via script_callbacks).
    Content renders directly inside Blocks — the WebUI wraps it in a tab via on_ui_tabs tuple.
    """
    import pathlib; csspath = pathlib.Path("style.css"); css_content = csspath.read_text(encoding="utf-8") if csspath.exists() else ""
    with gr.Blocks(analytics_enabled=False, elem_id="sdcf_main_blocks") as ui:
        if css_content:
            gr.HTML(f"<style>{css_content}</style>")
        _build_characters_content()
    return ui


def build_standalone_ui() -> gr.Blocks:
    """
    Build a standalone Gradio app for local development (no SD WebUI).
    Launch with: build_standalone_ui().launch(server_port=7861)
    """
    return build_ui()


# ---------------------------------------------------------------------------
# Dev launcher (python -m wildcard_creator.ui)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7861
    app = build_standalone_ui()
    app.launch(server_port=port, server_name="127.0.0.1", share=False)
