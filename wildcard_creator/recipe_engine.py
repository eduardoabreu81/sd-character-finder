"""
RecipeEngine — resolves __wildcard__ references in recipe templates.

Syntax supported:
  __category__          → picks random variant from wildcards/category.txt
  __category/sub__      → picks random variant from wildcards/category/sub.txt
  __pack:category__     → picks from a different pack (cross-pack refs)

Recipe YAML format (sd-dynamic-prompts compatible):
  PACK_NAME:
    RECIPE_DISPLAY_NAME:
      Entry_Name:
      - "positive template __hair__ __eyes__"
      - negative: "negative template __base_negative__"
"""

import re
import random
from typing import Optional

import yaml

from wildcard_creator import pack_manager as pm

# Pattern: __some/category/path__ (letters, digits, /, _, -)
_WC_PATTERN = re.compile(r"__([a-zA-Z0-9_/\-]+)__")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _pick_variant(pack_name: str, category_path: str) -> str:
    """
    Resolve a category path to a random non-empty variant.
    category_path may be 'hair', 'hair/color', etc.
    Also handles 'category_negative' for explicit negative refs.
    """
    # Normalise slashes
    category_path = category_path.replace("\\", "/")

    # Determine if it's a nested path (contains /) or a top-level category
    parts = category_path.split("/")
    if len(parts) == 1:
        # top-level
        variants = pm.read_variants(pack_name, category_path)
    else:
        # sub-path: wildcards/hair/color.txt
        from wildcard_creator.pack_manager import get_packs_dir
        file_path = get_packs_dir() / pack_name / "wildcards" / "/".join(parts[:-1]) / f"{parts[-1]}.txt"
        if file_path.exists():
            variants = [l for l in file_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        else:
            variants = []

    if not variants:
        return f"({category_path})"  # fallback: return the ref itself as hint

    return random.choice(variants).strip()


def resolve_template(template: str, pack_name: str, roll: bool = True) -> str:
    """
    Replace all __category__ tokens in a template with a variant from the pack.
    If roll=False, returns the template unchanged (for display purposes).
    """
    if not roll:
        return template

    def replacer(match: re.Match) -> str:
        cat = match.group(1)
        return _pick_variant(pack_name, cat)

    return _WC_PATTERN.sub(replacer, template)


# ---------------------------------------------------------------------------
# Recipe YAML parsing
# ---------------------------------------------------------------------------

def parse_recipe_yaml(yaml_content: str) -> dict:
    """Parse recipe YAML. Returns nested dict."""
    try:
        return yaml.safe_load(yaml_content) or {}
    except Exception as e:
        return {"__error__": str(e)}


def _flatten_recipes(data: dict, prefix: str = "") -> list[dict]:
    """
    Flatten nested YAML into a list of recipe entries.
    Each entry: {name, positive_template, negative_template}

    Handles multiple formats:
      Format A — list with one string:
        Entry:
        - "positive template"

      Format B — list with pos + neg:
        Entry:
        - "positive template"
        - negative: "negative template"

      Format C — dict with pos/neg keys:
        Entry:
          positive: "..."
          negative: "..."
    """
    recipes = []
    for key, value in data.items():
        full_name = f"{prefix}/{key}" if prefix else key

        if isinstance(value, list):
            # Format A or B
            positive = ""
            negative = ""
            for item in value:
                if isinstance(item, str):
                    positive = item
                elif isinstance(item, dict):
                    negative = item.get("negative", item.get("negative_prompt", ""))
            recipes.append({
                "name": full_name,
                "display_name": key,
                "positive_template": positive,
                "negative_template": negative
            })

        elif isinstance(value, dict):
            # Could be Format C or nested group
            if "positive" in value or "negative" in value:
                # Format C
                recipes.append({
                    "name": full_name,
                    "display_name": key,
                    "positive_template": value.get("positive", value.get("positive_prompt", "")),
                    "negative_template": value.get("negative", value.get("negative_prompt", ""))
                })
            else:
                # Nested group — recurse
                recipes.extend(_flatten_recipes(value, prefix=full_name))

        elif value is None:
            # Empty entry — placeholder
            pass

    return recipes


def get_recipe_entries(pack_name: str, recipe_name: str) -> list[dict]:
    """Return flat list of recipe entries from a recipe YAML file."""
    raw = pm.read_recipe_raw(pack_name, recipe_name)
    if not raw:
        return []
    data = parse_recipe_yaml(raw)
    return _flatten_recipes(data)


# ---------------------------------------------------------------------------
# High-level roll
# ---------------------------------------------------------------------------

def roll_recipe_entry(pack_name: str, entry: dict) -> tuple[str, str]:
    """
    Roll (randomize) a recipe entry.
    Returns (positive_prompt, negative_prompt).
    """
    positive = resolve_template(entry.get("positive_template", ""), pack_name)
    negative = resolve_template(entry.get("negative_template", ""), pack_name)
    return positive, negative


def roll_recipe(pack_name: str, recipe_name: str, entry_name: Optional[str] = None) -> tuple[str, str]:
    """
    Roll prompts for a recipe.
    If entry_name is None, picks the first entry.
    Returns (positive, negative).
    """
    entries = get_recipe_entries(pack_name, recipe_name)
    if not entries:
        return "", ""

    if entry_name:
        matching = [e for e in entries if e["name"] == entry_name or e["display_name"] == entry_name]
        entry = matching[0] if matching else entries[0]
    else:
        entry = entries[0]

    return roll_recipe_entry(pack_name, entry)


# ---------------------------------------------------------------------------
# YAML recipe builder (for Recipe Editor)
# ---------------------------------------------------------------------------

def build_recipe_yaml(pack_name: str, recipe_display_name: str, entries: list[dict]) -> str:
    """
    Build a recipe YAML string from a list of entry dicts.
    Each entry: {name, positive_template, negative_template}
    """
    data = {pack_name: {recipe_display_name: {}}}
    inner = data[pack_name][recipe_display_name]
    for entry in entries:
        item = [entry["positive_template"]]
        if entry.get("negative_template"):
            item.append({"negative": entry["negative_template"]})
        inner[entry["name"]] = item

    return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# Category reference scanner
# ---------------------------------------------------------------------------

def find_wildcard_refs(template: str) -> list[str]:
    """Return all unique __category__ references found in a template."""
    return list(dict.fromkeys(_WC_PATTERN.findall(template)))
