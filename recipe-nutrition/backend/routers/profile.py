"""
profile.py — 사용자 프로필 API (개인 맞춤형 추천용)

엔드포인트:
  POST /api/profile               프로필 생성 (회원가입 시 선호도 설정)
  GET  /api/profile/{user_id}     프로필 조회
  PUT  /api/profile/{user_id}/weights   선호도(가중치) 변경
  POST /api/profile/{user_id}/log       먹은 음식 기록 추가
"""
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import profile_service

router = APIRouter(prefix="/api/profile", tags=["profile"])


class WeightsIn(BaseModel):
    price:   float = 0.25
    protein: float = 0.22
    calorie: float = 0.18
    sodium:  float = 0.15
    time:    float = 0.20


class CreateProfileIn(BaseModel):
    weights: Optional[WeightsIn] = None


class FoodLogIn(BaseModel):
    food_name: str = Field(..., min_length=1)


@router.post("")
async def create_profile(body: CreateProfileIn):
    weights = body.weights.model_dump() if body.weights else None
    return profile_service.create_profile(weights)


@router.get("/{user_id}")
async def get_profile(user_id: str):
    p = profile_service.get_profile(user_id)
    if not p:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return p


@router.put("/{user_id}/weights")
async def update_weights(user_id: str, body: WeightsIn):
    p = profile_service.update_weights(user_id, body.model_dump())
    if not p:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return p


@router.post("/{user_id}/log")
async def add_food_log(user_id: str, body: FoodLogIn):
    p = profile_service.add_food_log(user_id, body.food_name)
    if not p:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return p
