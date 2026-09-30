"""
routers/user.py
---------------
즐겨찾기(favorites) · 별점(ratings) API 엔드포인트.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from services import user_data_service

router = APIRouter(prefix="/api/user", tags=["user"])


class FavoriteItem(BaseModel):
    recipe_id: str
    name:      str
    image_url: Optional[str] = ""


class RatingItem(BaseModel):
    recipe_id:   str
    recipe_name: str
    score:       int = Field(..., ge=0, le=5)


# ── 즐겨찾기 ──────────────────────────────────────────────────

@router.get("/favorites")
def list_favorites():
    return {"items": user_data_service.get_favorites()}


@router.post("/favorites")
def add_favorite(item: FavoriteItem):
    items = user_data_service.add_favorite(item.recipe_id, item.name, item.image_url or "")
    return {"ok": True, "items": items}


@router.delete("/favorites/{recipe_id}")
def remove_favorite(recipe_id: str):
    items = user_data_service.remove_favorite(recipe_id)
    return {"ok": True, "items": items}


@router.get("/favorites/{recipe_id}/check")
def check_favorite(recipe_id: str):
    return {"is_favorite": user_data_service.is_favorite(recipe_id)}


# ── 별점 ──────────────────────────────────────────────────────

@router.get("/ratings")
def list_ratings():
    return user_data_service.get_ratings()


@router.post("/ratings")
def set_rating(item: RatingItem):
    ratings = user_data_service.set_rating(item.recipe_id, item.recipe_name, item.score)
    return {"ok": True, "ratings": ratings}


@router.get("/ratings/{recipe_id}")
def get_rating(recipe_id: str):
    score = user_data_service.get_rating(recipe_id)
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