"""
nutrition_service.py

[재료별 영양성분을 구하는 우선순위]
1. 로컬 시드 캐시 (LOCAL_NUTRITION_100G) — 국가표준식품성분표 대표값 기준,
   70여 개 자주 쓰이는 재료를 미리 채워둠. API 호출 없이 즉시 응답.
2. AI 캐시 파일 (nutrition_ai_cache.json) — 예전에 한 번 AI가 추정해서
   저장해둔 값이 있으면 재사용.
3. 위 둘 다 없을 때만 AI에게 배치로 물어봐서 채움 → 파일 캐시에 영구 저장
   (Gemini 우선, 429/오류 시 llm_service가 내부적으로 Groq로 자동 전환).

[FIX 2] AI 응답을 "재료명을 key로 하는 JSON"으로 받으면, AI가 한글
재료명을 요청한 것과 미세하게 다르게 표기(띄어쓰기, 조사 등)할 경우 key가
안 맞아서 매칭 실패 → 조용히 0으로 남는 문제가 있었음. 이번엔 "보낸 순서
그대로 배열로 응답"하도록 바꿔서, 값은 인덱스(순서)로만 매칭한다 —
문자열이 완전히 똑같아야 할 필요가 없어져서 훨씬 안정적임.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from services import llm_service

# ─────────────────────────────────────────────────────────────
# 재료명 동의어 매핑
# ─────────────────────────────────────────────────────────────
ALIASES = {
    "감자": ["감자"], "고구마": ["고구마"], "양배추": ["양배추"],
    "배추": ["배추", "김치배추"], "당근": ["당근"],
    "두부": ["두부", "부침두부", "찌개두부"], "순두부": ["순두부"],
    "콩비지": ["콩비지", "비지"],
    "돼지고기": ["돼지고기", "돈육", "돼지", "삼겹살", "목살", "앞다리살"],
    "소고기": ["소고기", "쇠고기", "우육", "불고기용소고기", "한우"],
    "닭고기": ["닭고기", "계육", "닭볶음탕용닭", "닭다리"],
    "닭가슴살": ["닭가슴살"],
    "청양고추": ["청양고추"], "고추": ["고추", "홍고추", "풋고추", "붉은고추", "붉은 고추"],
    "부침가루": ["부침가루", "튀김가루", "밀가루", "전분가루", "감자전분"],
    "달걀": ["달걀", "계란", "메추리알"], "계란": ["계란", "달걀"],
    "식용유": ["식용유", "콩기름", "대두유", "카놀라유", "포도씨유"],
    "참기름": ["참기름", "들기름"],
    "오렌지": ["오렌지"], "오렌지즙": ["오렌지즙"],
    "간장": ["간장", "진간장", "양조간장", "국간장", "저염간장"],
    "된장": ["된장", "저염된장"], "고추장": ["고추장"], "쌈장": ["쌈장"],
    "양파": ["양파"], "대파": ["대파", "파", "쪽파"],
    "마늘": ["마늘", "다진마늘", "깐마늘", "양념 다진 마늘", "다진 마늘"],
    "생강": ["생강", "다진생강"],
    "토마토": ["토마토"], "방울토마토": ["방울토마토", "대추토마토"],
    "사과": ["사과"], "배": ["배"], "귤": ["귤"], "레몬": ["레몬"],
    "김치": ["김치", "배추김치", "묵은지"],
    "애호박": ["애호박", "호박"], "단호박": ["단호박"],
    "오이": ["오이"], "무": ["무", "무우"],
    "버섯": ["버섯", "느타리버섯", "표고버섯", "새송이버섯", "팽이버섯"],
    "브로콜리": ["브로콜리"], "시금치": ["시금치"], "부추": ["부추"],
    "콩나물": ["콩나물"], "숙주": ["숙주", "숙주나물"],
    "상추": ["상추", "양상추"], "깻잎": ["깻잎"],
    "미나리": ["미나리"], "쑥갓": ["쑥갓"],
    "미역": ["미역", "건미역"], "다시마": ["다시마"],
    "쌀": ["쌀", "밥", "찹쌀", "현미"],
    "국수": ["국수", "소면", "칼국수면", "우동면"],
    "새우": ["새우", "칵테일새우"], "오징어": ["오징어"],
    "조개": ["조개", "바지락", "모시조개"], "굴": ["굴"],
    "멸치": ["멸치", "국물멸치"],
    "황태": ["황태", "황태채", "북어", "북어채"],
    "대구": ["대구"], "고등어": ["고등어"], "연어": ["연어"],
    "치즈": ["치즈", "슬라이스치즈", "모짜렐라치즈", "체다치즈"],
    "우유": ["우유"], "생크림": ["생크림"], "버터": ["버터"],
    "요거트": ["요거트", "플레인요거트"],
    "베이컨": ["베이컨"], "소시지": ["소시지"], "햄": ["햄", "스팸"],
    "설탕": ["설탕", "백설탕", "황설탕"], "꿀": ["꿀"],
    "식초": ["식초", "현미식초", "사과식초"],
    "고춧가루": ["고춧가루"], "들깻가루": ["들깻가루", "들깨가루"],
    "카레가루": ["카레가루", "카레"], "빵": ["빵", "식빵"],
    "견과류": ["견과류", "아몬드", "호두", "땅콩"],
    "소금": ["소금", "천일염"],
}

_FLAT_ALIASES = sorted(
    ((alias, canonical) for canonical, vals in ALIASES.items() for alias in vals),
    key=lambda pair: len(pair[0]),
    reverse=True,
)  # 긴 별칭부터 매칭 (예: "닭가슴살"이 "닭"에 걸려 닭고기로 잘못 매칭되는 것 방지)

# ─────────────────────────────────────────────────────────────
# 로컬 시드 캐시 — 국가표준식품성분표 대표값 근사치 (100g 기준)
# [FIX 1] 이전 버전에서 실수로 30여개로 축소하며 "순두부" 등이 빠졌던 것을
# 70여개로 복원. 자주 쓰는 재료는 최대한 이 표에서 바로 해결하고,
# 여기 없는 재료만 아래 AI 배치 추정으로 넘어가게 함.
# ─────────────────────────────────────────────────────────────
LOCAL_NUTRITION_100G: Dict[str, Dict[str, float]] = {
    "감자":     {"protein_g": 2.0,  "fat_g": 0.1,  "carb_g": 17.0, "sugar_g": 1.0, "fiber_g": 1.7, "sodium_mg": 5,   "calcium_mg": 8},
    "고구마":   {"protein_g": 1.4,  "fat_g": 0.2,  "carb_g": 28.0, "sugar_g": 4.7, "fiber_g": 2.5, "sodium_mg": 6,   "calcium_mg": 22},
    "양배추":   {"protein_g": 1.3,  "fat_g": 0.1,  "carb_g": 5.8,  "sugar_g": 3.2, "fiber_g": 2.3, "sodium_mg": 15,  "calcium_mg": 42},
    "배추":     {"protein_g": 1.2,  "fat_g": 0.2,  "carb_g": 3.5,  "sugar_g": 1.5, "fiber_g": 1.8, "sodium_mg": 8,   "calcium_mg": 44},
    "당근":     {"protein_g": 0.9,  "fat_g": 0.2,  "carb_g": 9.6,  "sugar_g": 4.5, "fiber_g": 2.8, "sodium_mg": 60,  "calcium_mg": 30},
    "두부":     {"protein_g": 8.0,  "fat_g": 4.8,  "carb_g": 1.9,  "sugar_g": 0.5, "fiber_g": 0.4, "sodium_mg": 8,   "calcium_mg": 105},
    "순두부":   {"protein_g": 4.2,  "fat_g": 2.3,  "carb_g": 1.5,  "sugar_g": 0.4, "fiber_g": 0.2, "sodium_mg": 6,   "calcium_mg": 60},
    "콩비지":   {"protein_g": 4.5,  "fat_g": 2.0,  "carb_g": 6.0,  "sugar_g": 0.5, "fiber_g": 3.0, "sodium_mg": 5,   "calcium_mg": 70},
    "돼지고기": {"protein_g": 17.0, "fat_g": 20.0, "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 55,  "calcium_mg": 5},
    "소고기":   {"protein_g": 20.0, "fat_g": 14.0, "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 50,  "calcium_mg": 5},
    "닭고기":   {"protein_g": 20.0, "fat_g": 8.0,  "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 70,  "calcium_mg": 10},
    "닭가슴살": {"protein_g": 23.0, "fat_g": 1.5,  "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 65,  "calcium_mg": 6},
    "청양고추": {"protein_g": 1.9,  "fat_g": 0.4,  "carb_g": 8.8,  "sugar_g": 4.0, "fiber_g": 3.4, "sodium_mg": 3,   "calcium_mg": 15},
    "고추":     {"protein_g": 1.9,  "fat_g": 0.4,  "carb_g": 8.8,  "sugar_g": 4.0, "fiber_g": 3.4, "sodium_mg": 3,   "calcium_mg": 15},
    "부침가루": {"protein_g": 7.0,  "fat_g": 1.5,  "carb_g": 76.0, "sugar_g": 1.0, "fiber_g": 2.5, "sodium_mg": 400, "calcium_mg": 20},
    "달걀":     {"protein_g": 12.6, "fat_g": 10.6, "carb_g": 0.7,  "sugar_g": 0.4, "fiber_g": 0.0, "sodium_mg": 130, "calcium_mg": 55},
    "계란":     {"protein_g": 12.6, "fat_g": 10.6, "carb_g": 0.7,  "sugar_g": 0.4, "fiber_g": 0.0, "sodium_mg": 130, "calcium_mg": 55},
    "식용유":   {"protein_g": 0.0,  "fat_g": 100.0,"carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 0,   "calcium_mg": 0},
    "참기름":   {"protein_g": 0.0,  "fat_g": 100.0,"carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 0,   "calcium_mg": 0},
    "오렌지":   {"protein_g": 0.9,  "fat_g": 0.1,  "carb_g": 11.8, "sugar_g": 9.4, "fiber_g": 2.4, "sodium_mg": 1,   "calcium_mg": 40},
    "오렌지즙": {"protein_g": 0.9,  "fat_g": 0.1,  "carb_g": 11.8, "sugar_g": 9.4, "fiber_g": 0.2, "sodium_mg": 1,   "calcium_mg": 10},
    "간장":     {"protein_g": 8.1,  "fat_g": 0.1,  "carb_g": 7.9,  "sugar_g": 2.0, "fiber_g": 0.0, "sodium_mg": 5493,"calcium_mg": 20},
    "된장":     {"protein_g": 12.0, "fat_g": 6.0,  "carb_g": 14.0, "sugar_g": 3.0, "fiber_g": 4.0, "sodium_mg": 3862,"calcium_mg": 90},
    "고추장":   {"protein_g": 4.8,  "fat_g": 1.1,  "carb_g": 43.0, "sugar_g": 14.0,"fiber_g": 3.5, "sodium_mg": 2000,"calcium_mg": 30},
    "쌈장":     {"protein_g": 8.0,  "fat_g": 4.0,  "carb_g": 25.0, "sugar_g": 8.0, "fiber_g": 3.0, "sodium_mg": 3000,"calcium_mg": 50},
    "양파":     {"protein_g": 1.1,  "fat_g": 0.1,  "carb_g": 9.3,  "sugar_g": 4.2, "fiber_g": 1.7, "sodium_mg": 4,   "calcium_mg": 20},
    "대파":     {"protein_g": 1.8,  "fat_g": 0.2,  "carb_g": 7.3,  "sugar_g": 2.3, "fiber_g": 2.6, "sodium_mg": 5,   "calcium_mg": 60},
    "마늘":     {"protein_g": 6.4,  "fat_g": 0.5,  "carb_g": 33.1, "sugar_g": 1.0, "fiber_g": 2.1, "sodium_mg": 9,   "calcium_mg": 25},
    "생강":     {"protein_g": 1.8,  "fat_g": 0.8,  "carb_g": 17.8, "sugar_g": 1.7, "fiber_g": 2.0, "sodium_mg": 13,  "calcium_mg": 16},
    "토마토":   {"protein_g": 0.9,  "fat_g": 0.2,  "carb_g": 3.9,  "sugar_g": 2.6, "fiber_g": 1.2, "sodium_mg": 5,   "calcium_mg": 8},
    "방울토마토": {"protein_g": 1.0,"fat_g": 0.2,  "carb_g": 4.0,  "sugar_g": 2.8, "fiber_g": 1.0, "sodium_mg": 5,   "calcium_mg": 8},
    "사과":     {"protein_g": 0.3,  "fat_g": 0.2,  "carb_g": 13.8, "sugar_g": 10.4,"fiber_g": 2.4, "sodium_mg": 1,   "calcium_mg": 6},
    "배":       {"protein_g": 0.3,  "fat_g": 0.1,  "carb_g": 11.4, "sugar_g": 8.9, "fiber_g": 2.3, "sodium_mg": 1,   "calcium_mg": 4},
    "귤":       {"protein_g": 0.7,  "fat_g": 0.2,  "carb_g": 11.0, "sugar_g": 8.5, "fiber_g": 1.5, "sodium_mg": 1,   "calcium_mg": 15},
    "레몬":     {"protein_g": 1.1,  "fat_g": 0.3,  "carb_g": 9.3,  "sugar_g": 2.5, "fiber_g": 2.8, "sodium_mg": 2,   "calcium_mg": 26},
    "김치":     {"protein_g": 1.8,  "fat_g": 0.5,  "carb_g": 4.0,  "sugar_g": 1.5, "fiber_g": 1.9, "sodium_mg": 500, "calcium_mg": 40},
    "애호박":   {"protein_g": 1.2,  "fat_g": 0.2,  "carb_g": 3.1,  "sugar_g": 1.7, "fiber_g": 1.1, "sodium_mg": 3,   "calcium_mg": 20},
    "단호박":   {"protein_g": 1.9,  "fat_g": 0.3,  "carb_g": 10.5, "sugar_g": 2.7, "fiber_g": 2.1, "sodium_mg": 1,   "calcium_mg": 30},
    "오이":     {"protein_g": 0.7,  "fat_g": 0.1,  "carb_g": 3.6,  "sugar_g": 1.7, "fiber_g": 0.6, "sodium_mg": 3,   "calcium_mg": 20},
    "무":       {"protein_g": 0.7,  "fat_g": 0.1,  "carb_g": 4.1,  "sugar_g": 2.4, "fiber_g": 1.4, "sodium_mg": 15,  "calcium_mg": 22},
    "버섯":     {"protein_g": 2.5,  "fat_g": 0.3,  "carb_g": 4.5,  "sugar_g": 1.0, "fiber_g": 2.0, "sodium_mg": 4,   "calcium_mg": 2},
    "브로콜리": {"protein_g": 3.7,  "fat_g": 0.4,  "carb_g": 6.6,  "sugar_g": 1.7, "fiber_g": 3.3, "sodium_mg": 40,  "calcium_mg": 47},
    "시금치":   {"protein_g": 2.9,  "fat_g": 0.4,  "carb_g": 3.6,  "sugar_g": 0.4, "fiber_g": 2.2, "sodium_mg": 79,  "calcium_mg": 99},
    "부추":     {"protein_g": 2.1,  "fat_g": 0.3,  "carb_g": 4.3,  "sugar_g": 1.5, "fiber_g": 2.8, "sodium_mg": 5,   "calcium_mg": 55},
    "콩나물":   {"protein_g": 3.6,  "fat_g": 0.5,  "carb_g": 3.9,  "sugar_g": 0.8, "fiber_g": 2.0, "sodium_mg": 2,   "calcium_mg": 33},
    "숙주":     {"protein_g": 2.0,  "fat_g": 0.1,  "carb_g": 3.2,  "sugar_g": 1.5, "fiber_g": 1.4, "sodium_mg": 3,   "calcium_mg": 12},
    "상추":     {"protein_g": 1.4,  "fat_g": 0.2,  "carb_g": 2.9,  "sugar_g": 1.0, "fiber_g": 1.3, "sodium_mg": 8,   "calcium_mg": 34},
    "깻잎":     {"protein_g": 4.0,  "fat_g": 0.6,  "carb_g": 6.7,  "sugar_g": 0.5, "fiber_g": 4.0, "sodium_mg": 5,   "calcium_mg": 215},
    "미나리":   {"protein_g": 2.2,  "fat_g": 0.3,  "carb_g": 3.4,  "sugar_g": 0.7, "fiber_g": 2.0, "sodium_mg": 40,  "calcium_mg": 60},
    "쑥갓":     {"protein_g": 2.3,  "fat_g": 0.3,  "carb_g": 3.7,  "sugar_g": 0.6, "fiber_g": 3.0, "sodium_mg": 60,  "calcium_mg": 90},
    "미역":     {"protein_g": 1.7,  "fat_g": 0.2,  "carb_g": 5.4,  "sugar_g": 0.4, "fiber_g": 3.6, "sodium_mg": 610, "calcium_mg": 155},
    "다시마":   {"protein_g": 1.7,  "fat_g": 0.2,  "carb_g": 9.6,  "sugar_g": 0.5, "fiber_g": 3.0, "sodium_mg": 2400,"calcium_mg": 708},
    "쌀":       {"protein_g": 6.4,  "fat_g": 0.7,  "carb_g": 79.5, "sugar_g": 0.1, "fiber_g": 0.6, "sodium_mg": 2,   "calcium_mg": 6},
    "국수":     {"protein_g": 10.0, "fat_g": 1.5,  "carb_g": 72.0, "sugar_g": 0.5, "fiber_g": 2.5, "sodium_mg": 8,   "calcium_mg": 15},
    "새우":     {"protein_g": 21.0, "fat_g": 1.7,  "carb_g": 0.2,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 200, "calcium_mg": 70},
    "오징어":   {"protein_g": 18.0, "fat_g": 1.7,  "carb_g": 1.4,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 250, "calcium_mg": 14},
    "조개":     {"protein_g": 12.0, "fat_g": 1.0,  "carb_g": 3.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 500, "calcium_mg": 100},
    "굴":       {"protein_g": 9.0,  "fat_g": 2.5,  "carb_g": 5.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 250, "calcium_mg": 80},
    "멸치":     {"protein_g": 43.0, "fat_g": 10.0, "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 3000,"calcium_mg": 1500},
    "황태":     {"protein_g": 68.0, "fat_g": 3.0,  "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 500, "calcium_mg": 200},
    "대구":     {"protein_g": 17.5, "fat_g": 0.7,  "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 90,  "calcium_mg": 20},
    "고등어":   {"protein_g": 21.0, "fat_g": 13.0, "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 90,  "calcium_mg": 15},
    "연어":     {"protein_g": 20.0, "fat_g": 13.0, "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 50,  "calcium_mg": 10},
    "치즈":     {"protein_g": 25.0, "fat_g": 33.0, "carb_g": 2.0,  "sugar_g": 0.5, "fiber_g": 0.0, "sodium_mg": 700, "calcium_mg": 700},
    "우유":     {"protein_g": 3.1,  "fat_g": 3.3,  "carb_g": 4.7,  "sugar_g": 4.7, "fiber_g": 0.0, "sodium_mg": 45,  "calcium_mg": 110},
    "생크림":   {"protein_g": 2.0,  "fat_g": 38.0, "carb_g": 3.0,  "sugar_g": 3.0, "fiber_g": 0.0, "sodium_mg": 40,  "calcium_mg": 65},
    "버터":     {"protein_g": 0.6,  "fat_g": 81.0, "carb_g": 0.1,  "sugar_g": 0.1, "fiber_g": 0.0, "sodium_mg": 640, "calcium_mg": 15},
    "요거트":   {"protein_g": 3.5,  "fat_g": 3.0,  "carb_g": 5.0,  "sugar_g": 5.0, "fiber_g": 0.0, "sodium_mg": 50,  "calcium_mg": 120},
    "베이컨":   {"protein_g": 13.0, "fat_g": 42.0, "carb_g": 1.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 1500,"calcium_mg": 10},
    "소시지":   {"protein_g": 13.0, "fat_g": 25.0, "carb_g": 3.0,  "sugar_g": 1.0, "fiber_g": 0.0, "sodium_mg": 900, "calcium_mg": 20},
    "햄":       {"protein_g": 15.0, "fat_g": 20.0, "carb_g": 2.0,  "sugar_g": 1.0, "fiber_g": 0.0, "sodium_mg": 1100,"calcium_mg": 10},
    "설탕":     {"protein_g": 0.0,  "fat_g": 0.0,  "carb_g": 99.8, "sugar_g": 99.8,"fiber_g": 0.0, "sodium_mg": 0,   "calcium_mg": 1},
    "꿀":       {"protein_g": 0.3,  "fat_g": 0.0,  "carb_g": 80.0, "sugar_g": 76.0,"fiber_g": 0.2, "sodium_mg": 5,   "calcium_mg": 6},
    "식초":     {"protein_g": 0.0,  "fat_g": 0.0,  "carb_g": 1.0,  "sugar_g": 0.2, "fiber_g": 0.0, "sodium_mg": 2,   "calcium_mg": 6},
    "고춧가루": {"protein_g": 15.0, "fat_g": 12.0, "carb_g": 45.0, "sugar_g": 10.0,"fiber_g": 30.0,"sodium_mg": 40,  "calcium_mg": 100},
    "들깻가루": {"protein_g": 18.0, "fat_g": 40.0, "carb_g": 20.0, "sugar_g": 1.0, "fiber_g": 20.0,"sodium_mg": 5,   "calcium_mg": 250},
    "카레가루": {"protein_g": 12.0, "fat_g": 12.0, "carb_g": 60.0, "sugar_g": 4.0, "fiber_g": 10.0,"sodium_mg": 1000,"calcium_mg": 200},
    "빵":       {"protein_g": 9.0,  "fat_g": 4.0,  "carb_g": 50.0, "sugar_g": 5.0, "fiber_g": 2.5, "sodium_mg": 450, "calcium_mg": 40},
    "견과류":   {"protein_g": 20.0, "fat_g": 50.0, "carb_g": 20.0, "sugar_g": 4.0, "fiber_g": 8.0, "sodium_mg": 5,   "calcium_mg": 80},
    "소금":     {"protein_g": 0.0,  "fat_g": 0.0,  "carb_g": 0.0,  "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 38758,"calcium_mg": 24},
}

_NUTRITION_FIELDS = ["protein_g", "fat_g", "carb_g", "sugar_g", "fiber_g", "sodium_mg", "calcium_mg"]

# ─────────────────────────────────────────────────────────────
# AI 추정값 영구 캐시
# ─────────────────────────────────────────────────────────────
_CACHE_DIR       = Path(__file__).parent / "cache"
_AI_CACHE_FILE   = _CACHE_DIR / "nutrition_ai_cache.json"
_CACHE_DIR.mkdir(exist_ok=True)


def _load_cache() -> Dict[str, Dict]:
    try:
        if _AI_CACHE_FILE.exists():
            return json.loads(_AI_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[nutrition_service] 캐시 로드 실패: {e}")
    return {}


def _save_cache() -> None:
    try:
        _AI_CACHE_FILE.write_text(
            json.dumps(_AI_CACHE, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[nutrition_service] 캐시 저장 실패: {e}")


_AI_CACHE: Dict[str, Dict] = _load_cache()


def _normalize_name(text: str) -> str:
    s = text or ""
    s = re.sub(r"^[●•·]\s*", "", s)
    s = re.sub(r"^(주재료|부재료|소스|양념|재료)\s*[:：]?\s*", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\d+(?:\.\d+)?\s*(kg|g|mg|ml|l|개|큰술|작은술|컵)", " ", s, flags=re.I)
    s = re.sub(r"\d+\s*/\s*\d+\s*개", " ", s)
    s = re.sub(r"[^\w가-힣]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    if s in ALIASES:
        return s

    # [FIX] "파"·"배"처럼 한 글자짜리 별칭은 단순 substring으로 검사하면
    # "아스파라거스"(파 포함)처럼 전혀 다른 재료가 잘못 매칭됨.
    # 1글자 별칭은 정확히 같은 단어일 때만 매칭하도록 제한.
    s_compact = s.replace(" ", "")
    for alias, canonical in _FLAT_ALIASES:
        if len(alias) == 1:
            if s_compact == alias:
                return canonical
        elif alias in s:
            return canonical
    return s


def _lookup(key: str) -> Optional[Dict]:
    if key in LOCAL_NUTRITION_100G:
        return LOCAL_NUTRITION_100G[key]
    if key in _AI_CACHE:
        return _AI_CACHE[key]
    return None


def has_local_or_cached(raw_name: str) -> bool:
    key = _normalize_name(raw_name)
    return bool(key) and _lookup(key) is not None


def _empty() -> Dict:
    return {
        "matched_name": "", "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0,
        "sugar_g": 0.0, "fiber_g": 0.0, "sodium_mg": 0.0, "calcium_mg": 0.0,
        "source": "",
    }


def _scale(key: str, base: Dict, amount_g: float, source: str) -> Dict:
    factor = amount_g / 100.0
    out = {"matched_name": key, "source": source}
    for f in _NUTRITION_FIELDS:
        out[f] = round(float(base.get(f, 0.0)) * factor, 2)
    return out


# ─────────────────────────────────────────────────────────────
# AI 배치 추정 — Gemini 우선, 429/오류 시 llm_service가 Groq로 자동 전환
# [FIX 2] 위치(배열 순서) 기반 매칭
# ─────────────────────────────────────────────────────────────
async def estimate_nutrition_batch(raw_names: List[str]) -> Dict[str, Dict]:
    keys = sorted({_normalize_name(n) for n in raw_names if _normalize_name(n)})
    keys = [k for k in keys if _lookup(k) is None]
    if not keys:
        return {}

    numbered = "\n".join(f"{i+1}. {k}" for i, k in enumerate(keys))
    prompt = f"""아래 번호가 매겨진 한국 요리 재료들의 "100g당" 영양성분을 추정하세요.
일반적으로 유통되는 형태(생재료 기준, 조리 전)를 가정하고, 정확히 모르는
재료라도 비슷한 식품군을 참고해서 합리적으로 추정하세요.

[재료 목록]
{numbered}

반드시 아래처럼 입력 순서와 개수가 정확히 같은 JSON 배열로만 반환하세요.
마크다운이나 설명 없이 배열만 반환하고, 각 원소는 순서대로 위 번호와 대응합니다:
[
  {{"protein_g": 숫자, "fat_g": 숫자, "carb_g": 숫자, "sugar_g": 숫자, "fiber_g": 숫자, "sodium_mg": 숫자, "calcium_mg": 숫자}},
  ...
]"""

    try:
        print(f"[nutrition_service] AI 영양성분 배치 추정 시작 ({len(keys)}개): {keys}")
        data, provider = await llm_service.generate_json(
            prompt,
            temperature=0.2,
            max_tokens=150 * max(len(keys), 1) + 200,
            as_object=False,  # 최상위가 배열([...])이라 Groq의 json_object 강제는 끔
        )

        if not isinstance(data, list):
            print(f"[nutrition_service] AI 응답이 배열이 아님({provider}), 원본: {str(data)[:300]}")
            return {}

        if len(data) != len(keys):
            print(f"[nutrition_service] AI 응답 개수 불일치({provider}): 요청 {len(keys)}개 / 응답 {len(data)}개 — 앞에서부터 맞는 만큼만 사용")

        filled = {}
        for k, row in zip(keys, data):
            if not isinstance(row, dict):
                continue
            entry = {f: round(float(row.get(f, 0.0) or 0.0), 2) for f in _NUTRITION_FIELDS}
            _AI_CACHE[k] = entry
            filled[k] = entry

        if filled:
            _save_cache()
        print(f"[nutrition_service] AI 영양성분 배치 완료({provider}): {len(filled)}/{len(keys)}건 성공")
        return filled

    except Exception as e:
        import traceback
        print(f"[nutrition_service] AI 영양성분 배치 오류 ({type(e).__name__}): {e}")
        traceback.print_exc()
        return {}


async def get_nutrition_for_ingredient(standard_nm: str, amount_g: float) -> Dict:
    if not standard_nm or amount_g <= 0:
        return _empty()

    key  = _normalize_name(standard_nm)
    base = _lookup(key)

    if base is not None:
        return _scale(key, base, amount_g, "nutrition_local" if key in LOCAL_NUTRITION_100G else "nutrition_ai")

    # [안전장치] recipe_service.py 의 배치 사전조회를 거치지 않은 경우를 대비
    await estimate_nutrition_batch([key])
    base = _lookup(key)
    if base is not None:
        return _scale(key, base, amount_g, "nutrition_ai")

    print(f"[nutrition_service] 최종 실패 — 0으로 표시됨: '{standard_nm}' (정규화: '{key}')")
    return _empty()