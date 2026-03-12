"""
tests/test_user_journey.py

End-to-end tests following the user journey:
  1. Create a pack
  2. Add categories with variants
  3. Create a recipe
  4. Generate (roll) prompts
  5. Export the pack as .zip
  6. Clean up

Each step builds on the previous, just like a real user session.
The packs directory is redirected to a temp folder — the real packs/ is never touched.
"""

import re
import sys
import zipfile
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Fixture: isolated packs directory
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_packs(tmp_path, monkeypatch):
    """Redirect all pack_manager I/O to a temp directory."""
    import wildcard_creator.pack_manager as pm

    monkeypatch.setattr(pm, "get_packs_dir", lambda: _make_packs_dir(tmp_path))
    yield tmp_path / "packs"


def _make_packs_dir(base: Path) -> Path:
    d = base / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Step 1 — Create a pack
# ---------------------------------------------------------------------------

class TestStep1_CreatePack:
    def test_creates_pack_directory(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")

        assert (isolated_packs / "my_test_pack").is_dir()
        assert (isolated_packs / "my_test_pack" / "wildcards").is_dir()
        assert (isolated_packs / "my_test_pack" / "recipes").is_dir()

    def test_creates_pack_json(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")
        meta = pm.get_pack_metadata("my_test_pack")

        assert meta["name"] == "my_test_pack"
        assert "version" in meta

    def test_creates_styles_csv(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")

        csv_path = isolated_packs / "my_test_pack" / "styles.csv"
        assert csv_path.exists()
        assert "name,prompt,negative_prompt" in csv_path.read_text(encoding="utf-8")

    def test_pack_appears_in_list(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")
        assert "my_test_pack" in pm.list_packs()

    def test_create_pack_idempotent(self, isolated_packs):
        """Creating the same pack twice must not raise or corrupt data."""
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")
        pm.create_pack("my_test_pack")  # second call
        assert pm.list_packs().count("my_test_pack") == 1


# ---------------------------------------------------------------------------
# Step 2 — Add categories and variants
# ---------------------------------------------------------------------------

class TestStep2_AddCategories:
    @pytest.fixture(autouse=True)
    def setup_pack(self, isolated_packs):
        import wildcard_creator.pack_manager as pm
        pm.create_pack("my_test_pack")

    def test_create_top_level_category(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_category("my_test_pack", "outfit")
        cats = pm.get_all_category_paths("my_test_pack")
        assert "outfit" in cats

    def test_create_nested_category(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_category("my_test_pack", "hair/color")
        cats = pm.get_all_category_paths("my_test_pack")
        assert "hair/color" in cats

    def test_save_and_read_variants(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        variants = ["blonde hair", "black hair", "red hair"]
        pm.save_category("my_test_pack", "hair/color", variants)

        read_back = pm.read_variants("my_test_pack", "hair/color")
        assert read_back == variants

    def test_save_and_read_negative_variants(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        positives = ["masterpiece, best quality"]
        negatives = ["lowres, bad anatomy"]
        pm.save_category("my_test_pack", "base", positives, negatives)

        assert pm.read_negative_variants("my_test_pack", "base") == negatives

    def test_save_category_with_description(self, isolated_packs):
        """description param must not cause TypeError (was a bug)."""
        import wildcard_creator.pack_manager as pm

        pm.save_category("my_test_pack", "base", ["masterpiece"], [], "Quality tags")
        # No exception = pass

    def test_empty_lines_stripped_on_save(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        variants = ["blonde hair", "", "  ", "black hair"]
        pm.save_category("my_test_pack", "hair/color", variants)

        read_back = pm.read_variants("my_test_pack", "hair/color")
        assert "" not in read_back
        assert "  " not in read_back
        assert len(read_back) == 2

    def test_delete_category_removes_files(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.save_category("my_test_pack", "outfit", ["casual jeans"], ["torn clothing"])
        pm.delete_category("my_test_pack", "outfit")

        assert pm.read_variants("my_test_pack", "outfit") == []
        assert pm.read_negative_variants("my_test_pack", "outfit") == []

    def test_all_category_paths_excludes_negatives(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.save_category("my_test_pack", "base", ["masterpiece"], ["lowres"])
        paths = pm.get_all_category_paths("my_test_pack")

        assert "base" in paths
        assert "base_negative" not in paths


# ---------------------------------------------------------------------------
# Step 3 — Create a recipe
# ---------------------------------------------------------------------------

SAMPLE_RECIPE_YAML = """\
my_test_pack:
  PORTRAIT:
    Simple Girl:
    - "__base__, 1girl, __hair/color__, __eyes/color__, __outfit__"
    - negative: "__base_negative__"
    Fantasy Girl:
    - "__base__, 1girl, fantasy, __hair/color__, __eyes/color__, armor"
    - negative: "__base_negative__, modern clothes"
"""

class TestStep3_CreateRecipe:
    @pytest.fixture(autouse=True)
    def setup_pack_with_categories(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")
        pm.save_category("my_test_pack", "base", ["masterpiece, best quality"])
        pm.save_category("my_test_pack", "base", ["masterpiece, best quality"],
                         ["lowres, bad anatomy"])
        pm.save_category("my_test_pack", "hair/color", ["blonde hair", "black hair", "red hair"])
        pm.save_category("my_test_pack", "eyes/color", ["blue eyes", "green eyes", "brown eyes"])
        pm.save_category("my_test_pack", "outfit", ["casual jeans", "elegant dress", "school uniform"])

    def test_save_recipe_creates_yaml_file(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)

        yaml_path = isolated_packs / "my_test_pack" / "recipes" / "portrait.yaml"
        assert yaml_path.exists()

    def test_recipe_appears_in_list(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)
        assert "portrait" in pm.list_recipes("my_test_pack")

    def test_read_recipe_raw_roundtrip(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)
        raw = pm.read_recipe_raw("my_test_pack", "portrait")
        assert "Simple Girl" in raw
        assert "Fantasy Girl" in raw

    def test_recipe_entries_parsed(self, isolated_packs):
        import wildcard_creator.pack_manager as pm
        from wildcard_creator import recipe_engine as re_engine

        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)
        entries = re_engine.get_recipe_entries("my_test_pack", "portrait")

        names = [e["display_name"] for e in entries]
        assert "Simple Girl" in names
        assert "Fantasy Girl" in names

    def test_entry_has_templates(self, isolated_packs):
        import wildcard_creator.pack_manager as pm
        from wildcard_creator import recipe_engine as re_engine

        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)
        entries = re_engine.get_recipe_entries("my_test_pack", "portrait")

        simple = next(e for e in entries if e["display_name"] == "Simple Girl")
        assert "__base__" in simple["positive_template"]
        assert "__hair/color__" in simple["positive_template"]
        assert "__base_negative__" in simple["negative_template"]

    def test_delete_recipe(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)
        pm.delete_recipe("my_test_pack", "portrait")

        assert "portrait" not in pm.list_recipes("my_test_pack")


# ---------------------------------------------------------------------------
# Step 4 — Generate (roll) prompts
# ---------------------------------------------------------------------------

_WC_RE = re.compile(r"__[a-zA-Z0-9_/\-]+__")


class TestStep4_GeneratePrompts:
    @pytest.fixture(autouse=True)
    def setup_full_pack(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")
        pm.save_category("my_test_pack", "base",
                         ["masterpiece, best quality"], ["lowres, bad anatomy"])
        pm.save_category("my_test_pack", "hair/color",
                         ["blonde hair", "black hair", "red hair"])
        pm.save_category("my_test_pack", "eyes/color",
                         ["blue eyes", "green eyes"])
        pm.save_category("my_test_pack", "outfit",
                         ["casual jeans", "elegant dress", "school uniform"])
        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)

    def test_roll_returns_non_empty_strings(self, isolated_packs):
        from wildcard_creator import recipe_engine as re_engine

        pos, neg = re_engine.roll_recipe("my_test_pack", "portrait")
        assert isinstance(pos, str) and len(pos) > 0
        assert isinstance(neg, str) and len(neg) > 0

    def test_roll_resolves_all_tokens(self, isolated_packs):
        """No __token__ must remain in the output after rolling."""
        from wildcard_creator import recipe_engine as re_engine

        for _ in range(10):  # roll multiple times for randomness coverage
            pos, neg = re_engine.roll_recipe("my_test_pack", "portrait")
            assert not _WC_RE.search(pos), f"Unresolved token in: {pos}"
            assert not _WC_RE.search(neg), f"Unresolved token in: {neg}"

    def test_roll_contains_real_variant(self, isolated_packs):
        """Rolled prompt should contain at least one known variant."""
        from wildcard_creator import recipe_engine as re_engine

        hair_variants = ["blonde hair", "black hair", "red hair"]
        pos, _ = re_engine.roll_recipe("my_test_pack", "portrait")
        assert any(v in pos for v in hair_variants), f"No hair variant found in: {pos}"

    def test_roll_specific_entry(self, isolated_packs):
        from wildcard_creator import recipe_engine as re_engine

        pos, neg = re_engine.roll_recipe("my_test_pack", "portrait", "Fantasy Girl")
        assert "fantasy" in pos.lower() or "armor" in pos.lower()

    def test_roll_missing_category_returns_fallback(self, isolated_packs):
        """Token with no backing file returns (category) not empty string."""
        from wildcard_creator import recipe_engine as re_engine

        result = re_engine.resolve_template("__nonexistent_cat__", "my_test_pack")
        assert result == "(nonexistent_cat)"

    def test_roll_no_mutation_of_template(self, isolated_packs):
        """Resolving a template does not modify the original YAML on disk."""
        import wildcard_creator.pack_manager as pm
        from wildcard_creator import recipe_engine as re_engine

        re_engine.roll_recipe("my_test_pack", "portrait")
        raw = pm.read_recipe_raw("my_test_pack", "portrait")
        assert "__base__" in raw  # tokens still in the YAML file


# ---------------------------------------------------------------------------
# Step 5 — Export the pack as .zip
# ---------------------------------------------------------------------------

class TestStep5_ExportPack:
    @pytest.fixture(autouse=True)
    def setup_full_pack(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        pm.create_pack("my_test_pack")
        pm.save_category("my_test_pack", "base", ["masterpiece"], ["lowres"])
        pm.save_category("my_test_pack", "hair/color", ["blonde hair"])
        pm.save_recipe_raw("my_test_pack", "portrait", SAMPLE_RECIPE_YAML)

    def test_export_returns_bytes(self, isolated_packs):
        import wildcard_creator.pack_manager as pm

        data = pm.export_pack_zip("my_test_pack")
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_export_is_valid_zip(self, isolated_packs):
        import wildcard_creator.pack_manager as pm
        import io

        data = pm.export_pack_zip("my_test_pack")
        assert zipfile.is_zipfile(io.BytesIO(data))

    def test_export_contains_expected_files(self, isolated_packs):
        import wildcard_creator.pack_manager as pm
        import io

        data = pm.export_pack_zip("my_test_pack")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()

        # Normalise to forward slashes
        names = [n.replace("\\", "/") for n in names]

        assert any("pack.json" in n for n in names)
        assert any("styles.csv" in n for n in names)
        assert any("base.txt" in n for n in names)
        assert any("hair/color.txt" in n for n in names)
        assert any("portrait.yaml" in n for n in names)

    def test_export_content_intact(self, isolated_packs):
        """Variants inside the zip match what was saved."""
        import wildcard_creator.pack_manager as pm
        import io

        data = pm.export_pack_zip("my_test_pack")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            base_txt = next(n for n in zf.namelist() if n.endswith("base.txt"))
            content = zf.read(base_txt).decode("utf-8")

        assert "masterpiece" in content
