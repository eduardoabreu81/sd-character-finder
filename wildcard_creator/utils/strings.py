"""
strings.py — String normalization utilities for SD Character Finder.

Functions:
- normalize_wildcard_name: for wildcard file names (lowercase, underscores, alphanum)
- normalize_for_danbooru: convert spaces to underscores, lowercase
- meaningful_words: extract meaningful words for name matching (stopwords removed)
"""

from __future__ import annotations

import re

_STOP_WORDS = {
    "the", "of", "a", "an", "in", "no", "to", "de", "la", "el", "wa", "ga",
    "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must", "i", "you", "he", "she", "it", "we", "they",
}

def normalize_wildcard_name(name: str) -> str:
    """Normalize a name for use as a wildcard file name.

    - Strip whitespace
    - Replace spaces with underscores
    - Lowercase
    - Remove any character not in [a-z0-9_-]
    """
    name = (name or "").strip().replace(" ", "_").lower()
    return re.sub(r"[^a-z0-9_\-]", "", name)

def normalize_for_danbooru(name: str) -> str:
    """Normalize a name for Danbooru tag queries.

    - Strip whitespace
    - Replace spaces with underscores
    - Lowercase
    """
    return name.strip().replace(" ", "_").lower()

def meaningful_words(name: str) -> set[str]:
    """Extract meaningful words from a name, excluding common stopwords.

    Used for matching DB names against Danbooru tags.
    """
    clean = name.lower().replace("_", " ")
    clean = re.sub(r"[()\\]", " ", clean)
    words = set(clean.split()) - _STOP_WORDS
    return {w for w in words if w}
