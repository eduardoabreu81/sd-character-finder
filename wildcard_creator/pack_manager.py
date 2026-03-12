"""
PackManager — CRUD for wildcard packs.

Pack structure:
  packs/<pack_name>/
    wildcards/
      <category>.txt          positive variants, one per line
      <category>_negative.txt negative variants, one per line
    recipes/
      <recipe_name>.yaml      sd-dynamic-prompts compatible YAML
    styles.csv                5-column styles file
    pack.json                 metadata (name, version, description, rating)
"""

import os
import json
import zipfile
import io
from pathlib import Path
from typing import Optional

import yaml


def _ext_dir() -> Path:
    return Path(__file__).parent.parent


def get_packs_dir() -> Path:
    d = _ext_dir() / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Pack-level operations
# ---------------------------------------------------------------------------

def list_packs() -> list[str]:
    """Return names of all pack directories."""
    packs_dir = get_packs_dir()
    return sorted(
        p.name for p in packs_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def create_pack(pack_name: str) -> Path:
    """Create pack directory structure. Returns pack path."""
    pack_path = get_packs_dir() / pack_name
    (pack_path / "wildcards").mkdir(parents=True, exist_ok=True)
    (pack_path / "recipes").mkdir(parents=True, exist_ok=True)
    meta_path = pack_path / "pack.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps({
            "name": pack_name,
            "version": "1.0",
            "description": "",
            "rating": "SFW",
            "author": ""
        }, indent=2), encoding="utf-8")
    styles_path = pack_path / "styles.csv"
    if not styles_path.exists():
        styles_path.write_text("name,prompt,negative_prompt,description,category\n", encoding="utf-8")
    return pack_path


def get_pack_metadata(pack_name: str) -> dict:
    meta_path = get_packs_dir() / pack_name / "pack.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"name": pack_name, "version": "1.0", "description": "", "rating": "SFW", "author": ""}


def save_pack_metadata(pack_name: str, meta: dict):
    pack_path = get_packs_dir() / pack_name
    pack_path.mkdir(parents=True, exist_ok=True)
    (pack_path / "pack.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def delete_pack(pack_name: str):
    import shutil
    pack_path = get_packs_dir() / pack_name
    if pack_path.exists():
        shutil.rmtree(pack_path)


# ---------------------------------------------------------------------------
# Category (wildcard file) operations
# ---------------------------------------------------------------------------

def list_categories(pack_name: str) -> list[str]:
    """Return category names (without _negative suffix, without .txt extension)."""
    wildcards_dir = get_packs_dir() / pack_name / "wildcards"
    if not wildcards_dir.exists():
        return []
    names = set()
    for f in wildcards_dir.glob("*.txt"):
        stem = f.stem
        if stem.endswith("_negative"):
            continue
        names.add(stem)
    return sorted(names)


def read_variants(pack_name: str, category: str) -> list[str]:
    """Read positive variants for a category. Returns list of non-empty lines."""
    path = get_packs_dir() / pack_name / "wildcards" / f"{category}.txt"
    if not path.exists():
        return []
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def read_negative_variants(pack_name: str, category: str) -> list[str]:
    path = get_packs_dir() / pack_name / "wildcards" / f"{category}_negative.txt"
    if not path.exists():
        return []
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_category(pack_name: str, category: str,
                  variants: list[str],
                  negative_variants: Optional[list[str]] = None,
                  description: str = ""):
    """Write positive (and optionally negative) variant files."""
    wc_dir = get_packs_dir() / pack_name / "wildcards"
    wc_dir.mkdir(parents=True, exist_ok=True)

    pos_path = wc_dir / f"{category}.txt"
    pos_path.parent.mkdir(parents=True, exist_ok=True)
    pos_path.write_text("\n".join(v for v in variants if v.strip()) + "\n", encoding="utf-8")

    if negative_variants is not None:
        neg_path = wc_dir / f"{category}_negative.txt"
        neg_path.write_text("\n".join(v for v in negative_variants if v.strip()) + "\n", encoding="utf-8")


def create_category(pack_name: str, category: str):
    """Create empty category files."""
    save_category(pack_name, category, [], [])


def delete_category(pack_name: str, category: str):
    wc_dir = get_packs_dir() / pack_name / "wildcards"
    for suffix in ["", "_negative"]:
        path = wc_dir / f"{category}{suffix}.txt"
        if path.exists():
            path.unlink()


def get_all_category_paths(pack_name: str) -> list[str]:
    """Return all category paths including sub-folder paths (e.g. 'hair/color')."""
    wildcards_dir = get_packs_dir() / pack_name / "wildcards"
    if not wildcards_dir.exists():
        return []
    paths = []
    for f in sorted(wildcards_dir.rglob("*.txt")):
        stem = f.stem
        if stem.endswith("_negative"):
            continue
        rel = f.relative_to(wildcards_dir).with_suffix("")
        paths.append(str(rel).replace("\\", "/"))
    return paths


# ---------------------------------------------------------------------------
# Recipe operations
# ---------------------------------------------------------------------------

def list_recipes(pack_name: str) -> list[str]:
    recipes_dir = get_packs_dir() / pack_name / "recipes"
    if not recipes_dir.exists():
        return []
    return sorted(f.stem for f in recipes_dir.glob("*.yaml"))


def read_recipe_raw(pack_name: str, recipe_name: str) -> str:
    path = get_packs_dir() / pack_name / "recipes" / f"{recipe_name}.yaml"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_recipe(pack_name: str, recipe_name: str) -> dict:
    raw = read_recipe_raw(pack_name, recipe_name)
    if not raw:
        return {}
    try:
        return yaml.safe_load(raw) or {}
    except Exception:
        return {}


def save_recipe_raw(pack_name: str, recipe_name: str, content: str):
    recipes_dir = get_packs_dir() / pack_name / "recipes"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    (recipes_dir / f"{recipe_name}.yaml").write_text(content, encoding="utf-8")


def save_recipe(pack_name: str, recipe_name: str, data: dict):
    save_recipe_raw(pack_name, recipe_name, yaml.dump(data, allow_unicode=True, sort_keys=False))


def delete_recipe(pack_name: str, recipe_name: str):
    path = get_packs_dir() / pack_name / "recipes" / f"{recipe_name}.yaml"
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Styles CSV
# ---------------------------------------------------------------------------

def read_styles_csv(pack_name: str) -> str:
    path = get_packs_dir() / pack_name / "styles.csv"
    if not path.exists():
        return "name,prompt,negative_prompt,description,category\n"
    return path.read_text(encoding="utf-8")


def save_styles_csv(pack_name: str, content: str):
    path = get_packs_dir() / pack_name / "styles.csv"
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_pack_zip(pack_name: str) -> bytes:
    """Return bytes of .zip containing the full pack structure."""
    pack_path = get_packs_dir() / pack_name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(pack_path.rglob("*")):
            if file_path.is_file():
                arcname = Path(pack_name) / file_path.relative_to(pack_path)
                zf.write(file_path, arcname)
    return buf.getvalue()
