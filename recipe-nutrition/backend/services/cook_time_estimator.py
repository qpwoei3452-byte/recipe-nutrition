"""
cook_time_estimator.py
─────────────────────────────────────────────────────────────
추천 순위 계산 시점에 사용할 "빠른 조리시간 추정" 모듈.

배경 (교수님 피드백 대응):
  - 식약처 API에는 조리시간 데이터가 없음
  - 기존 구조: 카드를 클릭해야 Gemini AI가 조리시간을 알려줌
    → 추천 순위(클릭 전)에는 조리시간이 0/기본값이라
      시간 가중치가 사실상 무의미했음
  - 해결: 메타데이터(조리단계 수, 조리방법, 카테고리)로
    추천 시점에 조리시간을 "추정"하여 순위에 반영.
    상세 화면에서는 기존처럼 Gemini가 정밀 분석 → 2단계 설계.

추정 근거:
  1) 조리단계 개수: 단계가 많을수록 조리시간이 김 (단계당 약 4분)
  2) 조리방법(RCP_WAY2): 굽기/튀기기/끓이기 등은 가산
  3) 단계 텍스트 내 명시 시간("30분", "1시간") 직접 추출 → 최우선
"""
import re
from typing import List, Dict, Optional

# 조리방법별 기본 가산 시간(분)
METHOD_BASE = {
    "끓이기": 15, "삶기": 15, "조림": 20, "찌기": 20,
    "굽기": 12, "볶음": 8, "부침": 8, "튀김": 12,
    "무침": 3, "비빔": 3, "절임": 5, "회": 3,
    "기타": 8,
}

# 카테고리별 보정(분)
CATEGORY_ADJUST = {
    "밥": 3, "국": 5, "찌개": 8, "탕": 10,
    "반찬": 0, "일품": 5, "후식": 5, "기타": 0,
}

# 단계 텍스트에서 시간 표현 추출용 정규식
_TIME_PATTERNS = [
    (re.compile(r"(\d+)\s*시간\s*(\d+)?\s*분?"), "hour_min"),
    (re.compile(r"(\d+)\s*분"), "min"),
]


def _extract_explicit_minutes(steps_text: str) -> Optional[int]:
    """조리단계 텍스트에 명시된 시간을 모두 더해 추정 (가장 신뢰도 높음)."""
    if not steps_text:
        return None
    total = 0
    found = False

    # "N시간 M분" 우선 처리
    for m in re.finditer(r"(\d+)\s*시간\s*(\d+)?\s*분?", steps_text):
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        total += h * 60 + mi
        found = True

    # 시간 표현이 제거된 텍스트에서 "N분" 추출 (중복 방지)
    text_wo_hour = re.sub(r"\d+\s*시간\s*\d*\s*분?", "", steps_text)
    for m in re.finditer(r"(\d+)\s*분", text_wo_hour):
        val = int(m.group(1))
        # 비현실적으로 큰 값(재우기 등)은 제외
        if val <= 90:
            total += val
            found = True

    return total if found and total > 0 else None


def estimate_cook_time(recipe: Dict) -> Dict:
    """
    레시피 메타데이터로 조리시간(분)을 추정.
    반환: {"cook_time_min": int, "cook_time_confidence": str, "cook_time_source": str}
    """
    steps = recipe.get("steps", []) or []
    step_descs = [s.get("desc", "") for s in steps if isinstance(s, dict)]
    steps_text = " ".join(step_descs)
    method = recipe.get("method", "") or ""
    category = recipe.get("category", "") or ""

    # 1) 단계 텍스트에 시간이 명시돼 있으면 그것을 우선 사용
    explicit = _extract_explicit_minutes(steps_text)
    if explicit is not None:
        return {
            "cook_time_min": min(explicit, 120),
            "cook_time_confidence": "medium",
            "cook_time_source": "조리단계 명시 시간 합산",
        }

    # 2) 메타데이터 기반 추정
    n_steps = len([d for d in step_descs if len(d.strip()) > 3])

    if n_steps == 0:
        # 단계 정보조차 없으면 방법/카테고리만으로 대략 추정
        base = METHOD_BASE.get(method, METHOD_BASE["기타"])
        adj = CATEGORY_ADJUST.get(category, 0)
        est = base + adj
        return {
            "cook_time_min": max(5, min(est, 120)),
            "cook_time_confidence": "low",
            "cook_time_source": "조리방법·카테고리 기반 추정",
        }

    # 단계당 약 4분 + 방법 가산 + 카테고리 보정
    per_step = 4
    base = METHOD_BASE.get(method, METHOD_BASE["기타"])
    adj = CATEGORY_ADJUST.get(category, 0)
    est = n_steps * per_step + base * 0.5 + adj

    return {
        "cook_time_min": max(5, min(round(est), 120)),
        "cook_time_confidence": "medium",
        "cook_time_source": f"조리단계 {n_steps}개 기반 추정",
    }


def enrich_with_cook_time(recipes: List[Dict]) -> List[Dict]:
    """추천 후보 리스트 전체에 추정 조리시간을 부여."""
    for r in recipes:
        # 이미 신뢰도 높은 값이 있으면 덮어쓰지 않음
        if r.get("cook_time_min") and r.get("cook_time_min") > 0 \
           and r.get("cook_time_confidence") == "high":
            continue
        est = estimate_cook_time(r)
        r["cook_time_min"] = est["cook_time_min"]
        r["cook_time_confidence"] = est["cook_time_confidence"]
        r["cook_time_source"] = est["cook_time_source"]
    return recipes
