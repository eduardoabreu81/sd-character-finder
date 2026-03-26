import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_FILE = Path(__file__).parent.parent / "data" / "search_history.json"
MAX_HISTORY = 20

class SearchHistoryDB:
    def __init__(self, path: Path = _DEFAULT_HISTORY_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._history: list[str] = []
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        if not self._path.exists():
            self._history = []
            self._loaded = True
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._history = [str(x) for x in data if str(x).strip()]
        except Exception as e:
            logger.error(f"Failed to load search_history.json: {e}")
            self._history = []
        self._loaded = True

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._history, f)
        except Exception as e:
            logger.error(f"Failed to save search_history.json: {e}")

    def get_all(self) -> list[str]:
        with self._lock:
            self._load()
            return list(self._history)

    def add(self, query: str):
        query = (query or "").strip()
        if not query:
            return
        with self._lock:
            self._load()
            if query in self._history:
                self._history.remove(query)
            self._history.insert(0, query)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[:MAX_HISTORY]
            self._save()

_history_instance = None

def get_search_history_db() -> SearchHistoryDB:
    global _history_instance
    if _history_instance is None:
        _history_instance = SearchHistoryDB()
    return _history_instance
