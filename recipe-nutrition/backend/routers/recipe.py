from typing import Any, Dict, List, Optional
import asyncio  # history 검색 등 다른 await에서 필요

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services import recipe_service
from services import recommend_service
from services import ai_service
from services import profile_service
from services import cook_time_estimator
from services import allergy_service
from services import cook_steps_service
from services import user_data_service   # ← 추가

router = APIRouter(prefix="/api/recipe", tags=["recipe"])


class RecipeSummary(BaseModel):
    id: str = ""
    name: str = ""
    category: str = "기타"
    method: str = "기타"
    calories: float = 0.0
    image_url: str = ""
    tags: List[str] = Field(default_factory=list)


class NutritionTotal(BaseModel):
    energy_kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carb_g: float = 0.0
    sugar_g: float = 0.0
    fiber_g: float = 0.0
    sodium_mg: float = 0.0
    calcium_mg: float = 0.0
    total_g: float = 0.0


class RecipeDetail(BaseModel):
    id: str = ""
    name: str = ""
    category: str = ""
    method: str = ""
    image_url: str = ""
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = "식약처"
    ingredients: List[Dict[str, Any]] = Field(default_factory=list)
    nutrition_total: NutritionTotal = Field(default_factory=NutritionTotal)
    price_total_krw: float = 0.0
    total_ingredient_g: float = 0.0
    servings: Optional[int] = None
    errors: List[str] = Field(default_factory=list)


@router.get("/search", response_model=List[RecipeSummary])
async def search(q: str = ""):
    return await recipe_service.search_recipes(q)


@router.get("/recommend")
async def recommend_recipes(
    q:            str   = "",
    mode:         str   = "기본",
    top_n:        int   = 0,
    user_id:      Optional[str]   = None,
    history:      str   = "",
    w_price:      Optional[float] = Query(default=None),
    w_protein:    Optional[float] = Query(default=None),
    w_calorie:    Optional[float] = Query(default=None),
    w_sodium:     Optional[float] = Query(default=None),
    w_time:       Optional[float] = Query(default=None),
    allergens:    str   = "",
    time_slot:    Optional[str]   = None,
    fridge:       str   = "",
    fridge_only:  bool  = False,
    fridge_mode:  str   = "boost",
):
    summaries = await recipe_service.search_recipes(q)
    if not summaries:
        return []

    # [FIX] asyncio.gather(get_recipe_detail × N) 방식 제거 → Railway 타임아웃 원인
    # 캐시된 raw MFDS 데이터에서 추천 점수 계산에 필요한 필드만 직접 추출(동기).
    # _format()의 재료별 영양·가격 API 호출이 없어서 수십 배 빠름.
    details = [recipe_service.get_recipe_for_scoring(r["id"]) for r in summaries]
    details = [d for d in details if d]

    cook_time_estimator.enrich_with_cook_time(details)

    user_weights    = None
    history_recipes = None

    if user_id:
        profile = profile_service.get_profile(user_id)
        if profile:
            user_weights = profile.get("weights")
            history_names = profile_service.get_food_history(user_id)
            if history_names:
                detail_by_name = {d.get("name"): d for d in details}
                hist_details = []
                missing = []
                for nm in history_names:
                    if nm in detail_by_name:
                        hist_details.append(detail_by_name[nm])
                    else:
                        missing.append(nm)
                for nm in missing[:5]:
                    found = await recipe_service.search_recipes(nm)
                    if found:
                        d = await recipe_service.get_recipe_detail(found[0]["id"], found[0]["name"],
                                                                  allow_ai=False)
                        if d:
                            hist_details.append(d)
                if hist_details:
                    cook_time_estimator.enrich_with_cook_time(hist_details)
                    recommend_service.normalize_scores(hist_details)
                    history_recipes = hist_details

    if user_weights is None and any(
        v is not None for v in (w_price, w_protein, w_calorie, w_sodium, w_time)
    ):
        user_weights = {
            "price":   w_price   if w_price   is not None else 0,
            "protein": w_protein if w_protein is not None else 0,
            "calorie": w_calorie if w_calorie is not None else 0,
            "sodium":  w_sodium  if w_sodium  is not None else 0,
            "time":    w_time    if w_time    is not None else 0,
        }

    direct_history = [s.strip() for s in (history or "").split(",") if s.strip()]
    similarity_map = {}

    if direct_history:
        recipe_names = [d.get("name", "") for d in details if d.get("name")]
        print(f"[recommend] AI 유사도 계산: 레시피 {len(recipe_names)}개 / 식단: {direct_history}")
        similarity_map = await ai_service.analyze_similarity_batch(recipe_names, direct_history)
        print(f"[recommend] AI 유사도 결과: {similarity_map}")

        detail_by_name = {d.get("name"): d for d in details}
        extra_hist = []
        existing_names = {h.get("name") for h in (history_recipes or [])}
        fetched_count = 0
        for nm in direct_history:
            if nm in existing_names:
                continue
            if nm in detail_by_name:
                extra_hist.append(detail_by_name[nm])
            elif fetched_count < 5:
                found = await recipe_service.search_recipes(nm)
                if found:
                    d = await recipe_service.get_recipe_detail(found[0]["id"], found[0]["name"],
                                                              allow_ai=False)
                    if d:
                        extra_hist.append(d)
                fetched_count += 1
        if extra_hist:
            cook_time_estimator.enrich_with_cook_time(extra_hist)
            recommend_service.normalize_scores(extra_hist)
            history_recipes = (history_recipes or []) + extra_hist

    excluded_allergens = [a.strip() for a in (allergens or "").split(",") if a.strip()]
    if excluded_allergens:
        details = allergy_service.filter_by_allergy(details, excluded_allergens)
        print(f"[recommend] 알레르기 필터링 후: {len(details)}개")

    fridge_items   = [f.strip() for f in (fridge or "").split(",") if f.strip()]
    liked_names    = user_data_service.get_liked_recipes(user_id or "")
    disliked_names = user_data_service.get_disliked_recipes(user_id or "")

    return recommend_service.recommend(
        details,
        mode=mode,
        top_n=top_n,
        user_weights=user_weights,
        w_price=w_price   if user_weights is None else None,
        w_protein=w_protein if user_weights is None else None,
        w_calorie=w_calorie if user_weights is None else None,
        w_sodium=w_sodium  if user_weights is None else None,
        w_time=w_time     if user_weights is None else None,
        user_history=direct_history,
        history_recipes=history_recipes,
        similarity_map=similarity_map,
        time_slot=time_slot,
        fridge_ingredients=fridge_items,
        fridge_only=fridge_only,
        fridge_mode=fridge_mode,
        liked_recipe_names=liked_names,
        disliked_recipe_names=disliked_names,
    )


@router.get("/{recipe_id}/detail", response_model=RecipeDetail)
async def detail(recipe_id: str, name: Optional[str] = Query(None)):
    print(f"[router] 요청 ID={recipe_id}, name={name}")
    res = await recipe_service.get_recipe_detail(recipe_id, name)
    if not res:
        raise HTTPException(status_code=404, detail="레시피를 찾을 수 없습니다.")
    return res


@router.get("/{recipe_id}/ai-analyze")
async def ai_analyze(
    recipe_id: str,
    name:      str = "",
    history:   str = "",
):
    detail = await recipe_service.get_recipe_detail(recipe_id, name)
    if not detail:
        raise HTTPException(status_code=404, detail="레시피를 찾을 수 없습니다.")

    steps = []
    for i in range(1, 21):
        s = (
            detail.get(f"manual{i:02d}", "") or
            detail.get(f"MANUAL{i:02d}", "") or ""
        )
        if s:
            steps.append(s)

    if not steps and detail.get("steps"):
        steps = [s.get("desc", "") for s in detail["steps"] if s.get("desc")]

    user_history = [h.strip() for h in history.split(",") if h.strip()]
    recipe_name  = name or detail.get("name", recipe_id)

    est = cook_time_estimator.estimate_cook_time(detail)
    ai_result = await ai_service.analyze_recipe(recipe_name, steps, user_history)

    if ai_result.get("cook_time_source") == "오류로 인한 기본값":
        ai_result["cook_time_min"]        = est["cook_time_min"]
        ai_result["cook_time_confidence"] = est["cook_time_confidence"]
        ai_result["cook_time_source"]     = est["cook_time_source"] + " (AI 분석 실패 대체)"

    detail.update({
        "cook_time_min":         ai_result["cook_time_min"],
        "cook_time_confidence":  ai_result["cook_time_confidence"],
        "cook_time_source":      ai_result["cook_time_source"],
        "recommendation_reason": ai_result["recommendation_reason"],
        "diet_similarity":        ai_result.get("diet_similarity", 0.0),
        "diet_similarity_reason": ai_result.get("diet_similarity_reason", ""),
        "similarity_score":      ai_result.get("similarity_score", 0.0),
        "similarity_reason":     ai_result.get("similarity_reason", ""),
    })
    return detail


@router.get("/{recipe_id}/easy-steps")
async def easy_steps(
    recipe_id: str,
    name:      str = "",
):
    detail = await recipe_service.get_recipe_detail(recipe_id, name)
    if not detail:
        raise HTTPException(status_code=404, detail="레시피를 찾을 수 없습니다.")

    raw_steps = [s.get("desc", "") for s in (detail.get("steps") or []) if s.get("desc")]
    if not raw_steps:
        return {"steps": []}

    ingredient_names = [
        ing.get("standard_nm") or ing.get("raw_name") or ""
        for ing in (detail.get("ingredients") or [])
    ]
    ingredient_names = [n for n in ingredient_names if n]

    recipe_name = name or detail.get("name", recipe_id)

    steps = await cook_steps_service.get_easy_steps(
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        original_steps=raw_steps,
        ingredient_names=ingredient_names,
    )
    return {"steps": steps}