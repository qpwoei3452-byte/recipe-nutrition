"""
user_data_service.py
--------------------
즐겨찾기(favorites)와 별점(ratings)을 JSON 파일로 영구 저장하는 서비스.
data/ 폴더 아래에 favorites.json, ratings.json 생성.

[FIX] 사용자별 분리
예전에는 모든 사용자의 별점·즐겨찾기가 한 덩어리로 저장됐다. 그래서
A가 준 별점이 B의 추천 점수를 바꿨고(recommend에서 liked/disliked로 사용),
B의 즐겨찾기 목록에 A가 담은 레시피가 보였다.
프로필(가중치)은 이미 user_id별로 저장되고 있었으므로 일관성도 깨져 있었다.

저장 구조 (schema 2):
    {
      "_schema": 2,
      "users": {
        "u_0300dac28a5b": { ... },
        "u_76977c12b68e": { ... }
      }
    }

기존 파일(schema 1, 평면 구조)은 자동으로 "__legacy__" 사용자 아래로
옮겨 보존한다. 소유자를 알 수 없는 데이터라 추천에는 쓰이지 않지만
삭제하지도 않는다.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FAVORITES_FILE = DATA_DIR / "favorites.json"
RATINGS_FILE   = DATA_DIR / "ratings.json"

SCHEMA_VERSION = 2
LEGACY_USER    = "__legacy__"   # 소유자 미상의 기존 데이터 보관용
ANON_USER      = "__anon__"     # user_id 없이 들어온 요청용

# [FIX] profile_service에는 있던 쓰기 잠금이 여기엔 없었다.
# 여러 요청이 동시에 저장하면 파일이 깨질 수 있다.
_LOCK = threading.Lock()


def _norm_uid(user_id: str) -> str:
    uid = (user_id or "").strip()
    return uid or ANON_USER


def _load(path: Path, legacy_key: str) -> dict:
    """파일을 읽어 schema 2 형태로 정규화해 돌려준다."""
    if not path.exists():
        return {"_schema": SCHEMA_VERSION, "users": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_schema": SCHEMA_VERSION, "users": {}}

    if isinstance(raw, dict) and raw.get("_schema") == SCHEMA_VERSION:
        raw.setdefault("users", {})
        return raw

    # ── schema 1 → 2 마이그레이션 ──
    legacy = raw if isinstance(raw, dict) else {}
    if legacy_key == "items":            # favorites.json: {"items": [...]}
        payload = legacy.get("items", [])
    else:                                # ratings.json: {recipe_id: {...}}
        payload = {k: v for k, v in legacy.items() if isinstance(v, dict)}

    migrated = {"_schema": SCHEMA_VERSION, "users": {}}
    if payload:
        migrated["users"][LEGACY_USER] = payload
        print(f"[user_data_service] {path.name}: 기존 데이터를 "
              f"'{LEGACY_USER}' 사용자로 이관했습니다 "
              f"({len(payload)}건, 추천에는 사용되지 않음)")
    return migrated


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["_schema"] = SCHEMA_VERSION
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)          # 쓰다 말고 죽어도 원본이 깨지지 않도록


# ── 즐겨찾기 ──────────────────────────────────────────────────

def get_favorites(user_id: str = "") -> list:
    uid = _norm_uid(user_id)
    return _load(FAVORITES_FILE, "items")["users"].get(uid, [])


def add_favorite(recipe_id: str, name: str, image_url: str = "",
                 user_id: str = "") -> list:
    uid = _norm_uid(user_id)
    with _LOCK:
        data  = _load(FAVORITES_FILE, "items")
        items = data["users"].get(uid, [])
        if not any(item.get("id") == recipe_id for item in items):
            items.append({
                "id":        recipe_id,
                "name":      name,
                "image_url": image_url,
                "added_at":  datetime.now().isoformat(),
            })
            data["users"][uid] = items
            _save(FAVORITES_FILE, data)
        return items


def remove_favorite(recipe_id: str, user_id: str = "") -> list:
    uid = _norm_uid(user_id)
    with _LOCK:
        data  = _load(FAVORITES_FILE, "items")
        items = [it for it in data["users"].get(uid, []) if it.get("id") != recipe_id]
        data["users"][uid] = items
        _save(FAVORITES_FILE, data)
        return items


def is_favorite(recipe_id: str, user_id: str = "") -> bool:
    return any(it.get("id") == recipe_id for it in get_favorites(user_id))


# ── 별점 ──────────────────────────────────────────────────────

def get_ratings(user_id: str = "") -> dict:
    uid = _norm_uid(user_id)
    return _load(RATINGS_FILE, "")["users"].get(uid, {})


def set_rating(recipe_id: str, recipe_name: str, score: int,
               user_id: str = "") -> dict:
    uid = _norm_uid(user_id)
    with _LOCK:
        data  = _load(RATINGS_FILE, "")
        mine  = data["users"].get(uid, {})
        if score == 0:
            mine.pop(recipe_id, None)
        else:
            mine[recipe_id] = {
                "name":     recipe_name,
                "score":    max(1, min(5, int(score))),
                "rated_at": datetime.now().isoformat(),
            }
        data["users"][uid] = mine
        _save(RATINGS_FILE, data)
        return mine


def get_rating(recipe_id: str, user_id: str = "") -> int:
    return get_ratings(user_id).get(recipe_id, {}).get("score", 0)


def get_liked_recipes(user_id: str = "") -> List[str]:
    """별점 4~5점 레시피 이름 목록 (추천 부스트용) — 해당 사용자 것만."""
    return [v["name"] for v in get_ratings(user_id).values()
            if v.get("score", 0) >= 4 and v.get("name")]


def get_disliked_recipes(user_id: str = "") -> List[str]:
    """별점 1~2점 레시피 이름 목록 (추천 페널티용) — 해당 사용자 것만."""
    return [v["name"] for v in get_ratings(user_id).values()
            if v.get("score", 0) <= 2 and v.get("name")]