import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_FAVORITES_FILE = Path(__file__).parent.parent / "data" / "favorites.json"

class FavoritesDB:
    def __init__(self, path: Path = _DEFAULT_FAVORITES_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._favorites: set[int] = set()
        self._loaded = False

    def _load(self, force: bool = False):
        if self._loaded and not force:
            return
        if not self._path.exists():
            self._favorites = set()
            self._loaded = True
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._favorites = set(int(k) for k in data if str(k).isdigit())
        except Exception as e:
            logger.error(f"Failed to load favorites.json: {e}")
            self._favorites = set()
        self._loaded = True

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._favorites), f)
        except Exception as e:
            logger.error(f"Failed to save favorites.json: {e}")

    def get_all(self) -> set[int]:
        with self._lock:
            self._load(force=True)
            return set(self._favorites)

    def is_favorite(self, char_id: int) -> bool:
        with self._lock:
            self._load(force=True)
            return char_id in self._favorites

    def toggle(self, char_id: int) -> bool:
        with self._lock:
            self._load(force=True)
            if char_id in self._favorites:
                self._favorites.remove(char_id)
                new_state = False
            else:
                self._favorites.add(char_id)
                new_state = True
            self._save()
            return new_state


_favorites_instance = None

def get_favorites_db() -> FavoritesDB:
    global _favorites_instance
    if _favorites_instance is None:
        _favorites_instance = FavoritesDB()
    return _favorites_instance
