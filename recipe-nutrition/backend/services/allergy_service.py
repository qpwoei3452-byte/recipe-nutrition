"""
allergy_service.py — 알레르기 필터링 서비스

allergy_map.json 기반으로 레시피에서 알레르기 유발 재료 포함 여부 판단.

사용:
  from services.allergy_service import filter_by_allergy
  safe_recipes = filter_by_allergy(recipes, ["게", "새우"])
"""

import json
from pathlib import Path
from typing import Dict, List, Set

_CACHE_DIR    = Path(__file__).parent / "cache"
_ALLERGY_FILE = _CACHE_DIR / "allergy_map.json"

# 메모리 캐시
_allergy_map: Dict[str, List[str]] = {}
_loaded = False


def _load():
    global _allergy_map, _loaded
    if _loaded:
        return
    try:
        if _ALLERGY_FILE.exists():
            _allergy_map = json.loads(_ALLERGY_FILE.read_text(encoding="utf-8"))
            print(f"[allergy_service] 로드 완료: {len(_allergy_map)}개 재료")
        else:
            print("[allergy_service] allergy_map.json 없음 — build_allergy_cache.py 먼저 실행하세요")
    except Exception as e:
        print(f"[allergy_service] 로드 실패: {e}")
    _loaded = True


# 식약처 22종 알레르기 목록
ALLERGY_22 = [
    "알류", "우유", "메밀", "땅콩", "대두", "밀",
    "고등어", "게", "새우", "돼지고기", "복숭아", "토마토",
    "아황산류", "호두", "닭고기", "쇠고기", "오징어", "조개류",
    "잣", "아몬드", "캐슈넛", "피스타치오"
]

# 알레르기 그룹 (사용자가 선택한 항목을 확장)
ALLERGY_GROUPS = {
    "알류":     ["알류", "달걀", "계란"],
    "우유":     ["우유", "유제품"],
    "대두":     ["대두", "콩"],
    "밀":       ["밀", "글루텐"],
    "게":       ["게", "갑각류"],
    "새우":     ["새우", "갑각류"],
    "오징어":   ["오징어", "연체류"],
    "조개류":   ["조개류", "연체류"],
    "쇠고기":   ["쇠고기", "소고기"],
}


def _contains_allergen(recipe: dict, excluded: Set[str]) -> bool:
    """레시피 재료 중 알레르기 유발 재료가 있으면 True."""
    _load()

    ingredients = recipe.get("ingredients", []) or []
    for ing in ingredients:
        name = ing.get("standard_nm") or ing.get("name") or ""
        name = name.strip()
        if not name:
            continue

        # 1) allergy_map에서 직접 조회
        allergens = _allergy_map.get(name, None)

        # 2) allergy_map에 없으면 부분 문자열 매칭으로 안전하게 처리
        if allergens is None:
            allergens = []
            for key, allergies in _allergy_map.items():
                if allergies and (key in name or name in key):
                    allergens.extend(allergies)

        # 3) 제외 목록과 교집합 확인
        for allergen in allergens:
            if allergen in excluded:
                return True

            # 그룹 확장 체크
            for group_key, group_list in ALLERGY_GROUPS.items():
                if allergen in group_list and group_key in excluded:
                    return True

    return False


def filter_by_allergy(
    recipes: List[dict],
    excluded_allergens: List[str],
) -> List[dict]:
    """
    알레르기 유발 재료가 포함된 레시피를 제외하고 반환.

    Args:
        recipes: 레시피 목록
        excluded_allergens: 제외할 알레르기 목록 (식약처 22종 기준)
                            예) ["게", "새우", "우유"]

    Returns:
        알레르기 재료가 없는 레시피 목록
    """
    if not excluded_allergens:
        return recipes

    _load()
    excluded = set(excluded_allergens)

    safe     = []
    excluded_count = 0
    for r in recipes:
        if _contains_allergen(r, excluded):
            excluded_count += 1
        else:
            safe.append(r)

    print(f"[allergy_service] 필터링: 전체 {len(recipes)}개 → 제외 {excluded_count}개 → 안전 {len(safe)}개")
    return safe


def get_allergens_in_recipe(recipe: dict) -> Dict[str, List[str]]:
    """레시피의 각 재료별 알레르기 정보 반환 (상세 페이지 표시용)."""
    _load()
    result = {}
    for ing in (recipe.get("ingredients", []) or []):
        name = (ing.get("standard_nm") or ing.get("name") or "").strip()
        if not name:
            continue
        allergens = _allergy_map.get(name, [])
        if allergens:
            result[name] = allergens
    return result
