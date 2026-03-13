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

import re
from pathlib import Path

import gradio as gr

from wildcard_creator import prompt_sender
from wildcard_creator.character_db import get_character_db
from wildcard_creator.danbooru import DanbooruDB


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
        "⚠️ Character database not found.\n\n"
        "Run the scraper to populate it:\n"
        "```\npython scripts/scrape_characters.py\n```\n"
        "(~14 min, 834 pages, ~20k characters)"
    )

    if not _populated:
        gr.Markdown(_NOT_POPULATED_MSG)
        return

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

        return labels, label_to_path

    _wildcard_dirs, _wildcard_dir_map = _discover_wildcard_dirs()

    gr.Markdown(
        f"### Browse {_total:,} Danbooru characters\n"
        "Search by name or tag, filter by series, then send to Generate."
    )

    with gr.Row():
        with gr.Column(scale=2):
            char_search = gr.Textbox(
                label="Search",
                placeholder="e.g. miku, saber, blue hair…",
                lines=1,
            )
        with gr.Column(scale=1):
            char_series = gr.Dropdown(
                label="Series",
                choices=_series_choices,
                value="All",
                interactive=True,
            )
        with gr.Column(scale=1):
            tag_status_filter = gr.Dropdown(
                label="Danbooru tag",
                choices=["All", "Missing Danbooru Tag", "Has Danbooru Tag"],
                value="All",
                interactive=True,
            )
        with gr.Column(scale=1, min_width=100):
            btn_char_search = gr.Button("🔍 Search", variant="primary")

    # Results table
    char_results = gr.Dataframe(
        headers=["name", "series", "rank"],
        datatype=["str", "str", "number"],
        label="Results",
        interactive=False,
        wrap=True,
    )
    char_results_state = gr.State([])  # full result list (with tags/image_url)

    gr.Markdown("---\n*Click a row above to load the character card.*")

    # Character card
    with gr.Row():
        with gr.Column(scale=1, min_width=260):
            char_image = gr.Image(
                label="Preview",
                height=280,
                interactive=False,
            )
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
                btn_char_send = gr.Button("➡️ Send to Generate", variant="primary")
                btn_char_add = gr.Button("➕ Add to txt2img")
                btn_char_copy = gr.Button("📋 Copy Tags")
                btn_char_save_tag = gr.Button("💾 Save Danbooru Tag")
            char_selected_id = gr.State(None)
            char_send_status = gr.Textbox(label="", interactive=False, max_lines=1)

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
                    interactive=True,
                )
                btn_export_wildcard_txt = gr.Button("💾 Save TXT wildcard")
            wildcard_dir_map_state = gr.State(_wildcard_dir_map)
            wildcard_export_status = gr.Textbox(label="", interactive=False, max_lines=1)

    # ----- Events -----

    def do_search(query, series, tag_status):
        query = (query or "").strip()
        series = (series or "All").strip() or "All"
        tag_status = (tag_status or "All").strip() or "All"
        try:
            results = cdb.search(
                query,
                series_filter=series if series != "All" else None,
                tag_status_filter=tag_status,
                limit=100,
            )
            table = [[r["name"], r["series"] or "", r["rank"]] for r in results]
            return table, results
        except Exception:
            return [], []

    def on_row_select(results_state, evt: gr.SelectData):
        row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        if not results_state or row_idx >= len(results_state):
            return None, "", "", "", "", None
        char = results_state[row_idx]
        canonical_tag = (char.get("danbooru_tag") or "").strip()
        # DB tags are mandatory — always use them as the prompt base.
        # canonical_tag is only a fallback when tags is empty.
        prompt_value = (char.get("tags") or canonical_tag or "").strip()
        return (
            char.get("image_url"),
            char["name"],
            char.get("series") or "",
            canonical_tag,
            prompt_value,
            char.get("id"),
        )

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
        return name

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
            lower_t = t.lower()
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

    def do_add_to_generate(tags):
        if not tags:
            return gr.update(value="⚠️ No tags to add")
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
        do_search,
        inputs=[char_search, char_series, tag_status_filter],
        outputs=[char_results, char_results_state],
    )
    char_search.submit(
        do_search,
        inputs=[char_search, char_series, tag_status_filter],
        outputs=[char_results, char_results_state],
    )
    char_results.select(
        on_row_select,
        inputs=[char_results_state],
        outputs=[char_image, char_name_out, char_series_out, char_danbooru_tag_out, char_tags_out, char_selected_id],
    )
    btn_char_save_tag.click(
        save_manual_danbooru_tag,
        inputs=[char_selected_id, char_danbooru_tag_out],
        outputs=[char_send_status, char_tags_out],
    )
    btn_char_send.click(
        fn=do_send_to_generate,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        js="""(tags) => {
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (promptEl && tags) {
                promptEl.value = tags;
                promptEl.dispatchEvent(new Event('input', {bubbles: true}));
            }
            return [tags];
        }"""
    )
    btn_char_add.click(
        fn=do_add_to_generate,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        js="""(tags) => {
            const promptEl = gradioApp().querySelector('#txt2img_prompt textarea');
            if (!promptEl || !tags) return [tags];

            const parse = (s) => (s || '').split(',').map(x => x.trim()).filter(Boolean);
            const existing = parse(promptEl.value);
            const incoming = parse(tags);
            const seen = new Set(existing.map(x => x.toLowerCase()));
            for (const tag of incoming) {
                const k = tag.toLowerCase();
                if (!seen.has(k)) {
                    existing.push(tag);
                    seen.add(k);
                }
            }

            promptEl.value = existing.join(', ');
            promptEl.dispatchEvent(new Event('input', {bubbles: true}));
            return [tags];
        }"""
    )
    btn_char_copy.click(
        fn=do_copy_tags,
        inputs=[char_tags_out],
        outputs=[char_send_status],
        js="""(tags) => {
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
        }"""
    )
    btn_export_wildcard_txt.click(
        fn=do_export_wildcard_txt,
        inputs=[wildcard_name, char_tags_out, wildcard_target_dir, wildcard_dir_map_state],
        outputs=[wildcard_export_status],
    )

    # =========================================================
    # Extra tags (discrete mode)
    # =========================================================
    with gr.Accordion("Extra tags from Danbooru (optional)", open=False):
        extra_enabled = gr.Checkbox(
            label="Enable extra-tag suggestions for selected character",
            value=False,
        )
        with gr.Row():
            btn_extra_fetch = gr.Button("Fetch extra tags")
            btn_extra_apply = gr.Button("Apply selected extras")
        extra_tag_choices = gr.CheckboxGroup(
            label="Suggested extra tags",
            choices=[],
            value=[],
            interactive=True,
            visible=False,
        )
        extra_tags_meta = gr.State({})
        extra_status = gr.Textbox(label="", interactive=False, max_lines=1)

    _live_db = DanbooruDB()

    def _fetch_extra_tags(enabled, selected_name, selected_series, manual_danbooru_tag):
        if not enabled:
            return gr.update(choices=[], value=[], visible=False), {}, gr.update(value="⚠️ Enable extra-tag suggestions first")

        seed = (manual_danbooru_tag or selected_name or "").strip()
        if not seed:
            return gr.update(choices=[], value=[], visible=False), {}, gr.update(value="⚠️ Select a character first")

        login, api_key = _get_default_danbooru_auth()
        try:
            tags = _live_db.fetch_character_post_tags(
                seed,
                login=login,
                api_key=api_key,
                n_posts=120,
                top_n=40,
                min_freq=0.08,
            )
        except Exception as exc:
            return gr.update(choices=[], value=[], visible=False), {}, gr.update(value=f"❌ {exc}")

        extras: list[str] = []
        category_map: dict[str, int] = {}
        for t in tags:
            tag = (t.get("tag") or "").strip()
            if not tag:
                continue
            extras.append(tag)
            category_map[tag.lower()] = int(t.get("category", 0))

        # Ensure character and series are always available in suggestions.
        selected_series = (selected_series or "").strip()
        if seed and seed.lower() not in category_map:
            extras.insert(0, seed)
            category_map[seed.lower()] = 4
        if selected_series and selected_series.lower() not in category_map:
            extras.insert(1 if extras else 0, selected_series)
            category_map[selected_series.lower()] = 3

        dedup_extras: list[str] = []
        seen = set()
        for tag in extras:
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            dedup_extras.append(tag)

        ordered = _order_tags_novelai_like(dedup_extras, category_map)
        if not ordered:
            return gr.update(choices=[], value=[], visible=False), {}, gr.update(value="⚠️ No useful extra tags found")

        default_selected = ordered[:20]
        return (
            gr.update(choices=ordered, value=default_selected, visible=True),
            category_map,
            gr.update(value=f"✅ Loaded {len(ordered)} extra tags"),
        )

    def _apply_extra_tags(enabled, current_prompt, selected_extras, category_map):
        if not enabled:
            return gr.update(), gr.update(value="⚠️ Enable extra-tag suggestions first")

        selected_extras = list(selected_extras or [])
        if not selected_extras:
            return gr.update(), gr.update(value="⚠️ Select at least one extra tag")

        current_parts = [p.strip() for p in (current_prompt or "").split(",") if p.strip()]
        seen = {p.lower() for p in current_parts}
        added = []
        for tag in selected_extras:
            if tag.lower() not in seen:
                current_parts.append(tag)
                seen.add(tag.lower())
                added.append(tag)

        ordered = _order_tags_novelai_like(current_parts, category_map or {})

        if not added:
            return gr.update(value=", ".join(ordered)), gr.update(value="ℹ️ All selected tags were already present")

        return (
            gr.update(value=", ".join(ordered)),
            gr.update(value=f"✅ Added {len(added)} extra tag(s)"),
        )

    btn_extra_fetch.click(
        _fetch_extra_tags,
        inputs=[extra_enabled, char_name_out, char_series_out, char_danbooru_tag_out],
        outputs=[extra_tag_choices, extra_tags_meta, extra_status],
    )

    btn_extra_apply.click(
        _apply_extra_tags,
        inputs=[extra_enabled, char_tags_out, extra_tag_choices, extra_tags_meta],
        outputs=[char_tags_out, extra_status],
    )


# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    """
    Build the full Gradio UI (attach to SD WebUI via script_callbacks).
    Content renders directly inside Blocks — the WebUI wraps it in a tab via on_ui_tabs tuple.
    """
    with gr.Blocks(analytics_enabled=False) as ui:
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
