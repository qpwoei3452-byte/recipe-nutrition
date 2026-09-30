"""
user_data_service.py
--------------------
즐겨찾기(favorites)와 별점(ratings)을 JSON 파일로 영구 저장하는 서비스.
data/ 폴더 아래에 favorites.json, ratings.json 생성.
"""

import json
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FAVORITES_FILE = DATA_DIR / "favorites.json"
RATINGS_FILE   = DATA_DIR / "ratings.json"


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 즐겨찾기 ──────────────────────────────────────────────────

def get_favorites() -> list:
    data = _load(FAVORITES_FILE)
    return data.get("items", [])


def add_favorite(recipe_id: str, name: str, image_url: str = "") -> list:
    data  = _load(FAVORITES_FILE)
    items = data.get("items", [])
    if not any(item["id"] == recipe_id for item in items):
        items.append({
            "id":        recipe_id,
            "name":      name,
            "image_url": image_url,
            "added_at":  datetime.now().isoformat(),
        })
        data["items"] = items
        _save(FAVORITES_FILE, data)
    return items


def remove_favorite(recipe_id: str) -> list:
    data  = _load(FAVORITES_FILE)
    items = [item for item in data.get("items", []) if item["id"] != recipe_id]
    data["items"] = items
    _save(FAVORITES_FILE, data)
    return items


def is_favorite(recipe_id: str) -> bool:
    return any(item["id"] == recipe_id for item in get_favorites())


# ── 별점 ──────────────────────────────────────────────────────

def get_ratings() -> dict:
    return _load(RATINGS_FILE)


def set_rating(recipe_id: str, recipe_name: str, score: int) -> dict:
    data = _load(RATINGS_FILE)
    if score == 0:
        data.pop(recipe_id, None)
    else:
        score = max(1, min(5, int(score)))
        data[recipe_id] = {
            "name":     recipe_name,
            "score":    score,
            "rated_at": datetime.now().isoformat(),
        }
    _save(RATINGS_FILE, data)
    return data


def get_rating(recipe_id: str) -> int:
    data = _load(RATINGS_FILE)
    return data.get(recipe_id, {}).get("score", 0)


def get_liked_recipes() -> list:
    """별점 4~5점 레시피 이름 목록 (추천 부스트용)."""
    data = _load(RATINGS_FILE)
    return [v["name"] for v in data.values() if v.get("score", 0) >= 4]


def get_disliked_recipes() -> list:
    """별점 1~2점 레시피 이름 목록 (추천 페널티용)."""
    data = _load(RATINGS_FILE)
    return [v["name"] for v in data.values() if v.get("score", 0) <= 2]