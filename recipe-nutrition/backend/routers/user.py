"""
routers/user.py
---------------
즐겨찾기(favorites) · 별점(ratings) API 엔드포인트.
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Optional

from services import user_data_service

router = APIRouter(prefix="/api/user", tags=["user"])


# [FIX] 즐겨찾기·별점이 모든 사용자 공용이었다. A가 준 별점이 B의 추천
# 점수를 바꾸고, B의 즐겨찾기 목록에 A가 담은 레시피가 보였다.
# user_id를 받아 사용자별로 분리한다. 값이 없으면 익명 사용자로 처리하므로
# 구버전 프론트가 호출해도 오류 없이 동작한다.
class FavoriteItem(BaseModel):
    recipe_id: str
    name:      str
    image_url: Optional[str] = ""
    user_id:   Optional[str] = ""


class RatingItem(BaseModel):
    recipe_id:   str
    recipe_name: str
    score:       int = Field(..., ge=0, le=5)
    user_id:     Optional[str] = ""


# ── 즐겨찾기 ──────────────────────────────────────────────────

@router.get("/favorites")
def list_favorites(user_id: str = Query("")):
    return {"items": user_data_service.get_favorites(user_id)}


@router.post("/favorites")
def add_favorite(item: FavoriteItem):
    items = user_data_service.add_favorite(
        item.recipe_id, item.name, item.image_url or "", item.user_id or "")
    return {"ok": True, "items": items}


@router.delete("/favorites/{recipe_id}")
def remove_favorite(recipe_id: str, user_id: str = Query("")):
    items = user_data_service.remove_favorite(recipe_id, user_id)
    return {"ok": True, "items": items}


@router.get("/favorites/{recipe_id}/check")
def check_favorite(recipe_id: str, user_id: str = Query("")):
    return {"is_favorite": user_data_service.is_favorite(recipe_id, user_id)}


# ── 별점 ──────────────────────────────────────────────────────

@router.get("/ratings")
def list_ratings(user_id: str = Query("")):
    return user_data_service.get_ratings(user_id)


@router.post("/ratings")
def set_rating(item: RatingItem):
    ratings = user_data_service.set_rating(
        item.recipe_id, item.recipe_name, item.score, item.user_id or "")
    return {"ok": True, "ratings": ratings}


@router.get("/ratings/{recipe_id}")
def get_rating(recipe_id: str, user_id: str = Query("")):
    score = user_data_service.get_rating(recipe_id, user_id)
    return {"recipe_id": recipe_id, "score": score}


# ── 시간대 슬롯 힌트 ──────────────────────────────────────────

@router.get("/time-slot")
def get_time_slot(hour: int):
    if 6 <= hour < 11:
        slot = "아침"
    elif 11 <= hour < 15:
        slot = "점심"
    elif 15 <= hour < 18:
        slot = "점심"   # 간식 = 점심 가중치
    elif 18 <= hour < 22:
        slot = "저녁"
    else:
        slot = "야식"
    return {"hour": hour, "time_slot": slot}