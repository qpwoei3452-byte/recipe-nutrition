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


# [FIX] allergy_map(1,120종)에 알레르겐 이름 자체가 키로 없는 경우가 많다.
# 예) '메밀', '땅콩' 단독 키가 없어 '메밀국수'·'땅콩소스'가 걸러지지 않았다.
# 식약처 표시대상 알레르기 유발물질을 보충 사전으로 두고, 재료명에 이
# 키워드가 들어 있으면 해당 알레르겐으로 간주한다. (안전 측 보강)
_CORE_ALLERGEN_KEYWORDS = {
    "메밀": "메밀",   "땅콩": "땅콩",   "호두": "호두",   "잣": "잣",
    "대두": "대두",   "콩가루": "대두", "두유": "대두",   "된장": "대두",
    "우유": "우유",   "치즈": "우유",   "생크림": "우유", "연유": "우유",
    "요거트": "우유", "요구르트": "우유",
    "달걀": "알류",   "계란": "알류",   "난백": "알류",   "난황": "알류",
    "새우": "새우",   "오징어": "오징어", "고등어": "고등어",
    "전복": "조개류", "홍합": "조개류", "바지락": "조개류",
    "복숭아": "복숭아", "토마토": "토마토",
    "돼지고기": "돼지고기", "닭고기": "닭고기",
    "쇠고기": "쇠고기", "소고기": "쇠고기",
    "밀가루": "밀",   "통밀": "밀",     "밀전병": "밀",
    "아황산": "아황산류",
}


def _core_allergens(name: str) -> List[str]:
    """재료명에 포함된 핵심 알레르겐 키워드를 찾는다.

    '밀'은 1글자라 '메밀'에 잘못 걸리므로 별도 처리한다.
    """
    found = []
    for kw, allergen in _CORE_ALLERGEN_KEYWORDS.items():
        if kw in name:
            found.append(allergen)
    # '밀' 단독: 메밀이 아닌 경우에만 (예: '밀면' O, '메밀면' X)
    if "밀" in name.replace("메밀", "") and "밀" not in found:
        found.append("밀")
    return found


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

        # 2) allergy_map에 없으면 부분 문자열 매칭
        #
        # [FIX] 기존에는 (key in name or name in key) 양방향 매칭이라
        # 짧은 재료명이 과도하게 걸렸다. 예를 들어 재료 '무'는 키 '무청'에
        # 포함되므로 무청의 알레르겐을 그대로 상속받았다.
        # 알레르기는 안전 기능이라 "넉넉하게 거르는 것"이 안전해 보이지만,
        # 엉뚱한 레시피가 사라지면 사용자가 기능 자체를 신뢰하지 않게 되고
        # 결국 꺼버리기 때문에 오히려 위험하다.
        # → 재료명이 키를 포함하는 방향만 인정하고(긴 쪽이 구체적),
        #   키가 2글자 이상일 때만 적용한다.
        if allergens is None:
            allergens = []
            for key, allergies in _allergy_map.items():
                if not allergies or len(key) < 2:
                    continue
                if key in name:          # '복숭아' ⊂ '복숭아통조림' → 인정
                    allergens.extend(allergies)

        # 2-b) 핵심 알레르겐 키워드 보충 (맵에 없는 항목 방어)
        allergens = list(allergens) + _core_allergens(name)

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