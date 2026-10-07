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
    "시금치": ["시금치"], "부추": ["부추"],
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

    "전분": ["전분", "녹말가루", "녹말", "물전분", "전분물", "타피오카 전분"],
    "브로콜리": ["브로콜리", "브로컬리", "브로콜리니"],
    "쌀가루": ["쌀가루", "멥쌀가루", "백미가루"],
    "어린잎채소": ["어린잎채소", "어린잎", "새싹채소", "새싹", "곁들임채소 어린잎", "새싹믹스"],
    "떡볶이떡": ["떡볶이떡", "떡볶이 떡", "가래떡", "누들 떡볶이 떡", "밀떡"],
    "와사비": ["와사비", "고추냉이", "연와사비"],
    "유부": ["유부", "조미유부"],
    "관자": ["관자", "패주", "가리비관자"],
    "가다랑어포": ["가다랑어포", "가쓰오부시", "가쓰오부시가루"],
    "셀러리": ["셀러리", "샐러리", "셀러리 줄기", "셀러리다진것"],
    "레드와인": ["레드와인", "적포도주", "와인"],
    "육수": ["육수", "닭육수", "치킨스톡", "닭 스톡", "멸치육수", "채소육수"],
    "닭육수": ["닭육수", "치킨스톡", "닭 스톡"],

    # [FIX] 같은 재료의 다른 표기를 하나로 묶는다.
    # '흰후추'·'통후추'·'백후추'·'후추가루'가 각각 따로 AI 조회되던 것을
    # '후추' 하나로 처리한다. 표기 차이만으로 중복 호출되던 낭비를 없앤다.
    "파인애플": ["배 저나트륨파인애플소스 파인애플", "파인애플 통조림", "파인애플 통조림 국물", "파인애플주스", "파인애플청", "파인애플통조림"],
    "바질잎": ["건바질", "바질 잎", "바질 페스토", "바질다진것", "바질마른것", "바질마른것 배"],
    "타임": ["건타임", "이탈리안시즈닝 타임", "타임 마른것", "타임다진것 0 5", "타임마른것"],
    "후추": ["백후추", "통후추", "후추가루", "흰후추"],
    "우엉": ["곁들이 샐러드 우엉", "뿌리채소조림 우엉", "소 우엉", "필수재료 우엉"],
    "옥수수": ["옥수수알", "옥수수콘", "캔 옥수수", "캔옥수수"],
    "누룽지": ["누룽지 50", "누룽지 밥", "누룽지가루 7 5", "시판 누룽지"],
    "오레가노": ["오레가노 다진것", "오레가노다진것", "오레가노마른것"],
    "오미자": ["오미자물", "오미자액", "오미자엑기스"],
    "겨자": ["발효겨자", "씨겨자", "적겨자"],
    "요구르트": ["플레인 요구르트", "플레인요구르트", "호상요구르트"],
    "수박": ["수박 속껍질", "수박껍질", "후추 소스 수박"],
    "매실원액": ["매실농축액", "매실엑기스", "매실장아찌"],
    "물파래": ["파래 10", "파래김", "파래김 0 5"],
    "월계수잎": ["월계수 잎", "월계수잎마른것"],
    "청경채": ["청경채 20", "필수 재료 청경채"],
    "완두콩": ["완두콩드레싱 삶은 완두콩", "완두콩알"],
    "계피": ["계피가루", "통계피"],
    "키위": ["키위샐러드 키위", "키위소스"],
    "아보카도": ["냉동 아보카도", "아보카도작은것"],
    "낙지": ["낙지 다리", "낙지다리"],
    "케일": ["보라로즈케일", "흰로즈케일"],
    "크림": ["화이트크림", "휘핑크림"],
    "망고": ["레드와인 200cc 망고", "망고퓨레"],
    "라임": ["라임주스", "라임즙"],
    "가자미": ["가자미 50", "가자미살"],
    "잡곡": ["잡곡밥", "잡곡밥흑미 검은콩"],
    "병아리콩": ["병아리콩 삶은 물", "불린 병아리콩"],
    "다크초콜릿": ["블랙초콜릿", "초콜릿 카카오매스"],
    "참나물 페스토 참나물": ["참나물 10", "필수 재료 참나물"],
    "파슬리가루": ["파슬리말린것"],
    "아스파라거스": ["곁들임채소 아스파라거스"],
    "라면": ["굵은 면발 라면"],
    "젤라틴": ["판젤라틴"],
    "스파게티": ["스파게티면"],
    "취나물": ["건취나물"],
    "귀리": ["귀리밥"],
    "애플민트": ["애플민트잎"],
    "포도": ["청포도"],
    "삼치": ["필수재료 삼치"],
    "딸기잼": ["냉동딸기"],
    "보리": ["찰보리"],
    "녹차가루": ["가루녹차"],
    "코코넛밀크": ["코코넛 밀크"],
    "청국장": ["생청국장"],
    "콜라비": ["필수재료 콜라비"],
    "한천": ["한천가루"],
    "달래": ["달래 5"],
    "소라": ["소라살"],
    "로즈메리": ["건로즈메리"],
    "민트": ["민트잎"],
    "토란": ["알토란"],
    "두반장": ["두반장 1"],
    "도토리묵": ["건도토리묵"],
    "수수": ["볶은수수"],
    "근대": ["적근대"],
    "코코넛오일": ["코코넛 오일"],
    "오리고기": ["필수 재료 오리고기"],
    "복숭아": ["천도복숭아"],
    "복분자": ["복분자소스 복분자"],
    "석류주스": ["석류 원액"],
    "레드치커리": ["그린치커리"],
    "가지 1": ["필수 재료 가지"],
    "천연조미료": ["수제조미료"],
    "꽁치": ["꽁치살"],
    "소불고기": ["필수 재료 소불고기"],
    "알비트": ["국물 비트"],
    "갈치": ["갈치구이 갈치"],
    "메이플시럽": ["아가베 시럽"],
    "자몽": ["자몽주수"],
    "옥수수가루": ["옥수수가루플렌타가루"],
    "분유": ["탈지분유"],
    "유자": ["유자필"],
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

    # 4차 — 정확 대응 항목이 없어 근사한 재료 (근거를 주석에 명시)
    "어린잎채소":                {"protein_g":   1.9, "fat_g":   0.4, "carb_g":   3.5, "sugar_g":   1.2, "fiber_g":   2.4, "sodium_mg":     17, "calcium_mg":    95},  # 어린잎·새싹 혼합 → 엽채류 대표값(상추)으로 근사
    "가다랑어포":                {"protein_g":  25.9, "fat_g":   1.8, "carb_g":   0.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     44, "calcium_mg":    15},  # 가쓰오부시 → 가다랑어 생것. 건조품이라 실제는 더 농축

    # 3차 보강 — 국가표준식품성분표에 다른 이름으로 등재된 재료
    "곶감":                   {"protein_g":   1.8, "fat_g":   0.1, "carb_g":  58.9, "sugar_g":  27.0, "fiber_g":   9.7, "sodium_mg":      1, "calcium_mg":    18},
    "관자":                   {"protein_g":  16.9, "fat_g":   0.3, "carb_g":   3.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    120, "calcium_mg":     7},
    "꽃게":                   {"protein_g":  16.2, "fat_g":   0.7, "carb_g":   0.4, "sugar_g":   0.4, "fiber_g":   0.0, "sodium_mg":    418, "calcium_mg":   127},
    "떡볶이떡":                 {"protein_g":   3.7, "fat_g":   0.4, "carb_g":  48.8, "sugar_g":   0.1, "fiber_g":   0.7, "sodium_mg":    261, "calcium_mg":    10},
    "백미":                   {"protein_g":   6.4, "fat_g":   1.1, "carb_g":  79.0, "sugar_g":   0.2, "fiber_g":   0.5, "sodium_mg":      2, "calcium_mg":     7},
    "수삼":                   {"protein_g":   4.1, "fat_g":   0.8, "carb_g":  18.9, "sugar_g":   8.1, "fiber_g":   2.4, "sodium_mg":     12, "calcium_mg":    84},
    "와사비":                  {"protein_g":   2.9, "fat_g":   0.5, "carb_g":  23.7, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      1, "calcium_mg":    41},
    "유부":                   {"protein_g":  26.1, "fat_g":  34.2, "carb_g":   7.9, "sugar_g":   0.4, "fiber_g":   1.5, "sodium_mg":      7, "calcium_mg":   584},
    "육수":                   {"protein_g":   1.3, "fat_g":   0.7, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     13, "calcium_mg":    17},
    "이스트":                  {"protein_g":  37.1, "fat_g":   6.8, "carb_g":  43.1, "sugar_g":   0.1, "fiber_g":  32.6, "sodium_mg":    120, "calcium_mg":    19},
    "적채":                   {"protein_g":   2.2, "fat_g":   0.2, "carb_g":   7.7, "sugar_g":   4.1, "fiber_g":   2.8, "sodium_mg":      6, "calcium_mg":    30},
    "참치":                   {"protein_g":  24.0, "fat_g":   8.1, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     62, "calcium_mg":    27},
    "청포묵":                  {"protein_g":   0.1, "fat_g":   0.0, "carb_g":   9.8, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     92, "calcium_mg":     5},
    "캐슈넛":                  {"protein_g":  16.8, "fat_g":  47.8, "carb_g":  30.2, "sugar_g":   5.0, "fiber_g":   3.3, "sodium_mg":    308, "calcium_mg":    43},
    "콜리플라워":                {"protein_g":   2.2, "fat_g":   0.5, "carb_g":   4.8, "sugar_g":   2.3, "fiber_g":   4.6, "sodium_mg":     13, "calcium_mg":    14},
    "홍시":                   {"protein_g":   0.4, "fat_g":   0.1, "carb_g":  15.1, "sugar_g":  11.4, "fiber_g":   1.9, "sodium_mg":      1, "calcium_mg":     8},

    # 2차 보강
    "홍합":                   {"protein_g":  13.8, "fat_g":   1.2, "carb_g":   3.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    43},
    "베이킹파우더":               {"protein_g":   0.1, "fat_g":   0.0, "carb_g":  24.1, "sugar_g":   0.0, "fiber_g":   0.2, "sodium_mg":   7893, "calcium_mg":  7364},
    "레드와인":                 {"protein_g":   0.2, "fat_g":   0.0, "carb_g":   1.9, "sugar_g":   0.0, "fiber_g":   1.5, "sodium_mg":      2, "calcium_mg":     9},

    # 빈출 재료
    "케첩":                   {"protein_g":   1.8, "fat_g":   0.1, "carb_g":  29.2, "sugar_g":  20.8, "fiber_g":   1.8, "sodium_mg":   1056, "calcium_mg":    19},
    "올리고당":                 {"protein_g":   0.0, "fat_g":   0.0, "carb_g":  77.5, "sugar_g":  30.6, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     0},
    "빵가루":                  {"protein_g":  11.9, "fat_g":   2.0, "carb_g":  77.0, "sugar_g":   4.7, "fiber_g":   4.2, "sodium_mg":    306, "calcium_mg":    21},
    "정종":                   {"protein_g":   0.4, "fat_g":   0.0, "carb_g":   4.2, "sugar_g":   3.1, "fiber_g":   0.0, "sodium_mg":      3, "calcium_mg":     4},
    "닭육수":                  {"protein_g":   1.3, "fat_g":   0.7, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     13, "calcium_mg":    17},
    "굴소스":                  {"protein_g":   2.1, "fat_g":   0.1, "carb_g":  27.1, "sugar_g":  20.6, "fiber_g":   0.2, "sodium_mg":   4608, "calcium_mg":    12},
    "쌀가루":                  {"protein_g":   6.4, "fat_g":   1.1, "carb_g":  79.0, "sugar_g":   0.2, "fiber_g":   0.5, "sodium_mg":      2, "calcium_mg":     7},

    # 국가표준식품성분표 자동 매칭
    "후추":                   {"protein_g":  12.9, "fat_g":   5.0, "carb_g":  66.3, "sugar_g":   0.7, "fiber_g":  25.6, "sodium_mg":      6, "calcium_mg":   391},
    "전분":                   {"protein_g":   0.1, "fat_g":   0.0, "carb_g":  82.7, "sugar_g":   0.1, "fiber_g":   0.0, "sodium_mg":     22, "calcium_mg":     4},
    "즉석밥":                  {"protein_g":   2.1, "fat_g":   0.3, "carb_g":  33.6, "sugar_g":   1.0, "fiber_g":   1.2, "sodium_mg":      1, "calcium_mg":     5},
    "맛술":                   {"protein_g":   0.3, "fat_g":   0.3, "carb_g":  35.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     32, "calcium_mg":     1},
    "바나나":                  {"protein_g":   1.1, "fat_g":   0.2, "carb_g":  20.0, "sugar_g":  14.2, "fiber_g":   2.2, "sodium_mg":      0, "calcium_mg":     6},
    "파인애플":                 {"protein_g":   0.5, "fat_g":   0.1, "carb_g":  14.1, "sugar_g":  10.9, "fiber_g":   1.3, "sodium_mg":      0, "calcium_mg":    13},
    "월계수잎":                 {"protein_g":   7.6, "fat_g":   8.4, "carb_g":  75.0, "sugar_g":   0.0, "fiber_g":  26.3, "sodium_mg":     23, "calcium_mg":   834},
    "파슬리가루":                {"protein_g":  20.2, "fat_g":   3.4, "carb_g":  61.6, "sugar_g":   5.7, "fiber_g":  21.7, "sodium_mg":    630, "calcium_mg":  1129},
    "연근":                   {"protein_g":   1.6, "fat_g":   0.1, "carb_g":  17.3, "sugar_g":   1.8, "fiber_g":   3.3, "sodium_mg":     21, "calcium_mg":    28},
    "청경채":                  {"protein_g":   1.4, "fat_g":   0.1, "carb_g":   1.6, "sugar_g":   0.0, "fiber_g":   1.2, "sodium_mg":     17, "calcium_mg":    87},
    "완두콩":                  {"protein_g":   7.9, "fat_g":   0.4, "carb_g":  19.5, "sugar_g":   1.7, "fiber_g":   8.4, "sodium_mg":      0, "calcium_mg":    36},
    "계피":                   {"protein_g":   3.6, "fat_g":   1.1, "carb_g":  80.9, "sugar_g":   1.9, "fiber_g":  59.5, "sodium_mg":     18, "calcium_mg":  1280},
    "주꾸미":                  {"protein_g":  10.8, "fat_g":   0.5, "carb_g":   0.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    19},
    "오레가노":                 {"protein_g":   9.0, "fat_g":   4.3, "carb_g":  68.9, "sugar_g":   4.1, "fiber_g":  42.5, "sodium_mg":     25, "calcium_mg":  1597},
    "우엉":                   {"protein_g":   2.6, "fat_g":   0.1, "carb_g":  15.3, "sugar_g":   2.9, "fiber_g":   4.6, "sodium_mg":      6, "calcium_mg":    46},
    "젤라틴":                  {"protein_g":   7.8, "fat_g":   0.0, "carb_g":  90.5, "sugar_g":  86.0, "fiber_g":   0.0, "sodium_mg":    466, "calcium_mg":     3},
    "요구르트":                 {"protein_g":   1.3, "fat_g":   0.0, "carb_g":  15.2, "sugar_g":  12.5, "fiber_g":   0.6, "sodium_mg":     17, "calcium_mg":    45},
    "키위":                   {"protein_g":   0.8, "fat_g":   0.3, "carb_g":  14.0, "sugar_g":   7.1, "fiber_g":   2.1, "sodium_mg":      1, "calcium_mg":    19},
    "스파게티":                 {"protein_g":  12.6, "fat_g":   1.5, "carb_g":  74.5, "sugar_g":   2.0, "fiber_g":   2.7, "sodium_mg":      6, "calcium_mg":    24},
    "아스파라거스":               {"protein_g":   2.0, "fat_g":   0.3, "carb_g":   2.5, "sugar_g":   1.4, "fiber_g":   1.7, "sodium_mg":      3, "calcium_mg":    11},
    "바질잎":                  {"protein_g":   2.4, "fat_g":   0.7, "carb_g":   5.6, "sugar_g":   0.8, "fiber_g":   2.6, "sodium_mg":      3, "calcium_mg":   238},
    "라면":                   {"protein_g":   8.6, "fat_g":  12.6, "carb_g":  67.1, "sugar_g":   2.5, "fiber_g":   2.3, "sodium_mg":   1472, "calcium_mg":   203},
    "옥수수":                  {"protein_g":   4.0, "fat_g":   1.5, "carb_g":  23.4, "sugar_g":   4.9, "fiber_g":   3.1, "sodium_mg":      0, "calcium_mg":     3},
    "타임":                   {"protein_g":   6.5, "fat_g":   5.2, "carb_g":  69.8, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     13, "calcium_mg":  1700},
    "귀리":                   {"protein_g":   9.9, "fat_g":   8.8, "carb_g":  68.0, "sugar_g":   0.9, "fiber_g":   7.6, "sodium_mg":      3, "calcium_mg":    52},
    "강황가루":                 {"protein_g":   6.7, "fat_g":   3.2, "carb_g":  74.3, "sugar_g":   3.3, "fiber_g":  17.9, "sodium_mg":     19, "calcium_mg":   125},
    "고사리":                  {"protein_g":   2.9, "fat_g":   0.2, "carb_g":   3.8, "sugar_g":   0.2, "fiber_g":   3.4, "sodium_mg":      0, "calcium_mg":     9},
    "아보카도":                 {"protein_g":   2.0, "fat_g":  14.7, "carb_g":   8.5, "sugar_g":   0.7, "fiber_g":   6.7, "sodium_mg":      7, "calcium_mg":    12},
    "낙지":                   {"protein_g":  16.3, "fat_g":   0.4, "carb_g":   0.0, "sugar_g":   0.2, "fiber_g":   0.0, "sodium_mg":    479, "calcium_mg":    26},
    "오미자":                  {"protein_g":   1.9, "fat_g":   2.8, "carb_g":  14.2, "sugar_g":   1.7, "fiber_g":   6.0, "sodium_mg":      1, "calcium_mg":    15},
    "탄산수":                  {"protein_g":   0.0, "fat_g":   0.0, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      1, "calcium_mg":     1},
    "미숫가루":                 {"protein_g":  14.4, "fat_g":   5.3, "carb_g":  76.7, "sugar_g":   1.2, "fiber_g":  12.8, "sodium_mg":      5, "calcium_mg":    61},
    "케일":                   {"protein_g":   3.4, "fat_g":   0.4, "carb_g":   4.7, "sugar_g":   0.7, "fiber_g":   3.3, "sodium_mg":     47, "calcium_mg":   371},
    "겨자":                   {"protein_g":   3.0, "fat_g":   0.2, "carb_g":   4.2, "sugar_g":   0.0, "fiber_g":   2.6, "sodium_mg":     36, "calcium_mg":   256},
    "누룽지":                  {"protein_g":   8.0, "fat_g":   1.1, "carb_g":  88.8, "sugar_g":   0.1, "fiber_g":   2.3, "sodium_mg":      2, "calcium_mg":    11},
    "도라지":                  {"protein_g":   2.0, "fat_g":   0.1, "carb_g":  15.2, "sugar_g":   1.1, "fiber_g":   4.2, "sodium_mg":      3, "calcium_mg":    40},
    "연겨자":                  {"protein_g":   8.0, "fat_g":  12.7, "carb_g":  37.4, "sugar_g":  19.5, "fiber_g":  19.4, "sodium_mg":   1423, "calcium_mg":   101},
    "더덕":                   {"protein_g":   2.3, "fat_g":   0.8, "carb_g":  17.6, "sugar_g":   4.9, "fiber_g":   3.7, "sodium_mg":      0, "calcium_mg":    30},
    "취나물":                  {"protein_g":   4.2, "fat_g":   0.3, "carb_g":  11.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     38, "calcium_mg":    83},
    "포도":                   {"protein_g":   0.4, "fat_g":   0.1, "carb_g":  15.3, "sugar_g":  14.3, "fiber_g":   1.0, "sodium_mg":      1, "calcium_mg":     4},
    "칠리소스":                 {"protein_g":   1.8, "fat_g":   0.1, "carb_g":  26.3, "sugar_g":   0.0, "fiber_g":   1.9, "sodium_mg":   1200, "calcium_mg":    27},
    "체리":                   {"protein_g":   1.4, "fat_g":   0.1, "carb_g":  14.3, "sugar_g":   8.0, "fiber_g":   2.3, "sodium_mg":      1, "calcium_mg":    11},
    "어묵":                   {"protein_g":  11.4, "fat_g":   4.5, "carb_g":  20.7, "sugar_g":   3.5, "fiber_g":   0.3, "sodium_mg":    699, "calcium_mg":    49},
    "파슬리다진것":               {"protein_g":   2.4, "fat_g":   0.3, "carb_g":   3.4, "sugar_g":   0.4, "fiber_g":   2.2, "sodium_mg":     10, "calcium_mg":   149},
    "애플민트":                 {"protein_g":   2.8, "fat_g":   0.4, "carb_g":   4.7, "sugar_g":   0.0, "fiber_g":   3.7, "sodium_mg":      2, "calcium_mg":   153},
    "녹차가루":                 {"protein_g":  22.4, "fat_g":   2.5, "carb_g":  66.9, "sugar_g":   0.0, "fiber_g":  40.4, "sodium_mg":     23, "calcium_mg":   717},
    "망고":                   {"protein_g":   0.7, "fat_g":   0.1, "carb_g":  15.4, "sugar_g":  13.7, "fiber_g":   1.5, "sodium_mg":      0, "calcium_mg":     7},
    "문어":                   {"protein_g":  16.4, "fat_g":   0.7, "carb_g":   0.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    280, "calcium_mg":    16},
    "맛살":                   {"protein_g":   7.7, "fat_g":   1.1, "carb_g":  19.4, "sugar_g":   3.5, "fiber_g":   0.0, "sodium_mg":    668, "calcium_mg":   303},
    "은행":                   {"protein_g":   4.7, "fat_g":   1.5, "carb_g":  42.8, "sugar_g":   3.0, "fiber_g":   2.2, "sodium_mg":      1, "calcium_mg":     7},
    "삼치":                   {"protein_g":  20.1, "fat_g":   2.9, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     39, "calcium_mg":     5},
    "딸기잼":                  {"protein_g":   0.8, "fat_g":   0.1, "carb_g":   8.2, "sugar_g":   6.1, "fiber_g":   1.5, "sodium_mg":      1, "calcium_mg":    12},
    "보리":                   {"protein_g":   8.8, "fat_g":   1.7, "carb_g":  76.9, "sugar_g":   0.9, "fiber_g":  10.9, "sodium_mg":      3, "calcium_mg":    33},
    "크림":                   {"protein_g":   2.0, "fat_g":  37.8, "carb_g":   5.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     25, "calcium_mg":    63},
    "셀러리":                  {"protein_g":   1.0, "fat_g":   0.1, "carb_g":   3.9, "sugar_g":   1.2, "fiber_g":   2.2, "sodium_mg":     20, "calcium_mg":    88},
    "소라":                   {"protein_g":  20.7, "fat_g":   0.3, "carb_g":   4.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    92},
    "라임":                   {"protein_g":   0.7, "fat_g":   0.2, "carb_g":  10.5, "sugar_g":   1.7, "fiber_g":   2.8, "sodium_mg":      2, "calcium_mg":    33},
    "가자미":                  {"protein_g":  22.1, "fat_g":   3.7, "carb_g":   0.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    230, "calcium_mg":    40},
    "수박":                   {"protein_g":   0.8, "fat_g":   0.1, "carb_g":   7.6, "sugar_g":   7.1, "fiber_g":   0.2, "sodium_mg":      1, "calcium_mg":     6},
    "참외":                   {"protein_g":   0.6, "fat_g":   0.0, "carb_g":  10.5, "sugar_g":   8.8, "fiber_g":   1.1, "sodium_mg":      2, "calcium_mg":     5},
    "치자":                   {"protein_g":   1.3, "fat_g":   0.1, "carb_g":  14.9, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      8, "calcium_mg":    39},
    "날치알":                  {"protein_g":  22.2, "fat_g":   0.5, "carb_g":   0.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    20},
    "두릅":                   {"protein_g":   2.4, "fat_g":   0.2, "carb_g":   4.8, "sugar_g":   0.8, "fiber_g":   4.4, "sodium_mg":      2, "calcium_mg":    80},
    "장어":                   {"protein_g":  17.9, "fat_g":   9.9, "carb_g":   0.4, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    81},
    "청국장가루":                {"protein_g":  41.8, "fat_g":  21.6, "carb_g":  26.8, "sugar_g":   0.7, "fiber_g":  17.3, "sodium_mg":     12, "calcium_mg":   241},
    "매생이":                  {"protein_g":   3.9, "fat_g":   3.3, "carb_g":   8.2, "sugar_g":   0.1, "fiber_g":   6.5, "sodium_mg":    104, "calcium_mg":    91},
    "코코넛밀크":                {"protein_g":   2.3, "fat_g":  23.8, "carb_g":   5.5, "sugar_g":   3.3, "fiber_g":   2.2, "sodium_mg":     15, "calcium_mg":    16},
    "청국장":                  {"protein_g":  20.8, "fat_g":   9.6, "carb_g":  12.8, "sugar_g":   1.9, "fiber_g":   8.8, "sodium_mg":   1135, "calcium_mg":   137},
    "콜라비":                  {"protein_g":   1.2, "fat_g":   0.1, "carb_g":   5.2, "sugar_g":   1.6, "fiber_g":   2.4, "sodium_mg":      7, "calcium_mg":    42},
    "한천":                   {"protein_g":   2.3, "fat_g":   0.1, "carb_g":  74.6, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":   523},
    "달래":                   {"protein_g":   2.4, "fat_g":   0.3, "carb_g":  13.4, "sugar_g":   2.8, "fiber_g":   2.9, "sodium_mg":      4, "calcium_mg":    83},
    "로즈메리":                 {"protein_g":   4.9, "fat_g":  15.2, "carb_g":  64.1, "sugar_g":   0.0, "fiber_g":  42.6, "sodium_mg":     50, "calcium_mg":  1280},
    "민트":                   {"protein_g":  17.5, "fat_g":   6.1, "carb_g":  56.2, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     28, "calcium_mg":  1763},
    "코코넛오일":                {"protein_g":   0.0, "fat_g":  99.7, "carb_g":   0.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     18, "calcium_mg":    13},
    "잡곡":                   {"protein_g":   9.8, "fat_g":   2.1, "carb_g":  73.4, "sugar_g":   0.9, "fiber_g":   6.2, "sodium_mg":      4, "calcium_mg":    27},
    "복숭아":                  {"protein_g":   0.6, "fat_g":   0.0, "carb_g":  13.1, "sugar_g":   9.4, "fiber_g":   2.6, "sodium_mg":      0, "calcium_mg":     4},
    "병아리콩":                 {"protein_g":  17.8, "fat_g":   5.7, "carb_g":  63.3, "sugar_g":   2.5, "fiber_g":  14.5, "sodium_mg":      3, "calcium_mg":   130},
    "다크초콜릿":                {"protein_g":   7.8, "fat_g":  42.6, "carb_g":  45.9, "sugar_g":  24.0, "fiber_g":  10.9, "sodium_mg":     20, "calcium_mg":    73},
    "매실원액":                 {"protein_g":   1.1, "fat_g":   1.1, "carb_g":   7.8, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      3, "calcium_mg":    28},
    "물파래":                  {"protein_g":   2.2, "fat_g":   0.1, "carb_g":   3.0, "sugar_g":   0.0, "fiber_g":   2.1, "sodium_mg":    122, "calcium_mg":    55},
    "아욱":                   {"protein_g":   3.1, "fat_g":   0.3, "carb_g":   7.6, "sugar_g":   0.0, "fiber_g":   4.5, "sodium_mg":     37, "calcium_mg":   267},
    "연유":                   {"protein_g":   5.6, "fat_g":   5.7, "carb_g":  13.1, "sugar_g":   5.0, "fiber_g":   0.0, "sodium_mg":     87, "calcium_mg":   165},
    "바질가루":                 {"protein_g":   2.8, "fat_g":   0.7, "carb_g":   5.9, "sugar_g":   0.4, "fiber_g":   2.7, "sodium_mg":      1, "calcium_mg":   270},
    "라즈베리":                 {"protein_g":   1.2, "fat_g":   0.7, "carb_g":  11.9, "sugar_g":   4.4, "fiber_g":   6.5, "sodium_mg":      1, "calcium_mg":    25},
    "까나리액젓":                {"protein_g":  16.0, "fat_g":   4.8, "carb_g":   0.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    120, "calcium_mg":   338},
    "멜론":                   {"protein_g":   0.3, "fat_g":   0.1, "carb_g":   9.6, "sugar_g":   7.3, "fiber_g":   1.0, "sodium_mg":     25, "calcium_mg":    10},
    "옥수수전분":                {"protein_g":   0.2, "fat_g":   0.6, "carb_g":  89.6, "sugar_g":   0.1, "fiber_g":   0.4, "sodium_mg":      6, "calcium_mg":     3},
    "자두":                   {"protein_g":   0.5, "fat_g":   0.6, "carb_g":   5.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      1, "calcium_mg":     3},
    "토란":                   {"protein_g":   2.1, "fat_g":   0.1, "carb_g":  15.8, "sugar_g":   0.0, "fiber_g":   2.8, "sodium_mg":      2, "calcium_mg":    11},
    "두반장":                  {"protein_g":   3.0, "fat_g":   2.4, "carb_g":  15.1, "sugar_g":   7.6, "fiber_g":   3.9, "sodium_mg":   4602, "calcium_mg":    23},
    "도토리묵":                 {"protein_g":   0.3, "fat_g":   0.1, "carb_g":  11.2, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     76, "calcium_mg":    15},
    "수수":                   {"protein_g":  11.7, "fat_g":   3.0, "carb_g":  73.6, "sugar_g":   0.5, "fiber_g":   6.4, "sodium_mg":      6, "calcium_mg":     8},
    "근대":                   {"protein_g":   1.8, "fat_g":   0.2, "carb_g":   3.3, "sugar_g":   0.0, "fiber_g":   2.7, "sodium_mg":    173, "calcium_mg":    49},
    "오리고기":                 {"protein_g":  21.0, "fat_g":   3.1, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     83, "calcium_mg":    11},
    "참나물 페스토 참나물":          {"protein_g":   3.5, "fat_g":   0.4, "carb_g":   7.6, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      4, "calcium_mg":   102},
    "느타리":                  {"protein_g":   2.6, "fat_g":   0.1, "carb_g":   4.7, "sugar_g":   0.7, "fiber_g":   2.9, "sodium_mg":      2, "calcium_mg":     0},
    "퀴노아":                  {"protein_g":   9.6, "fat_g":   3.3, "carb_g":  72.6, "sugar_g":   1.3, "fiber_g":   7.7, "sodium_mg":      0, "calcium_mg":    63},
    "정향":                   {"protein_g":   7.2, "fat_g":  13.6, "carb_g":  66.4, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    280, "calcium_mg":   640},
    "시래기":                  {"protein_g":   1.8, "fat_g":   0.2, "carb_g":   6.2, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     75, "calcium_mg":   630},
    "기름":                   {"protein_g":   0.0, "fat_g":  99.8, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     0},
    "당귀잎":                  {"protein_g":   3.2, "fat_g":   0.4, "carb_g":   8.8, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      3, "calcium_mg":    80},
    "뽕잎가루":                 {"protein_g":  26.2, "fat_g":   3.0, "carb_g":  53.2, "sugar_g":   0.0, "fiber_g":  38.4, "sodium_mg":     11, "calcium_mg":  1348},
    "피스타치오":                {"protein_g":  26.0, "fat_g":  48.9, "carb_g":  20.8, "sugar_g":   8.2, "fiber_g":  10.0, "sodium_mg":      4, "calcium_mg":   101},
    "돌나물":                  {"protein_g":   1.2, "fat_g":   0.1, "carb_g":   3.2, "sugar_g":   0.0, "fiber_g":   1.0, "sodium_mg":      0, "calcium_mg":   190},
    "꼬막":                   {"protein_g":  12.6, "fat_g":   0.3, "carb_g":   1.6, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    83},
    "아귀":                   {"protein_g":  14.1, "fat_g":   0.2, "carb_g":   0.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    10},
    "조청":                   {"protein_g":   1.4, "fat_g":   0.3, "carb_g":  77.0, "sugar_g":  46.9, "fiber_g":   1.0, "sodium_mg":      3, "calcium_mg":     4},
    "무청":                   {"protein_g":   1.8, "fat_g":   0.4, "carb_g":   4.3, "sugar_g":   0.8, "fiber_g":   2.9, "sodium_mg":     45, "calcium_mg":   200},
    "건크랜베리":                {"protein_g":   0.5, "fat_g":   0.1, "carb_g":  12.0, "sugar_g":   4.3, "fiber_g":   3.6, "sodium_mg":      2, "calcium_mg":     8},
    "머스타드":                 {"protein_g":   7.7, "fat_g":   6.9, "carb_g":  11.4, "sugar_g":   2.4, "fiber_g":   9.0, "sodium_mg":   1953, "calcium_mg":   133},
    "식혜":                   {"protein_g":   0.1, "fat_g":   0.0, "carb_g":   7.9, "sugar_g":   5.9, "fiber_g":   1.0, "sodium_mg":      2, "calcium_mg":     3},
    "대추고":                  {"protein_g":   1.4, "fat_g":   0.1, "carb_g":  27.6, "sugar_g":  24.3, "fiber_g":   3.0, "sodium_mg":      1, "calcium_mg":    14},
    "스테비아":                 {"protein_g":   2.4, "fat_g":   0.3, "carb_g":   8.7, "sugar_g":   0.0, "fiber_g":   5.4, "sodium_mg":      1, "calcium_mg":   200},
    "복분자":                  {"protein_g":   1.3, "fat_g":   0.7, "carb_g":  14.7, "sugar_g":   5.9, "fiber_g":   7.0, "sodium_mg":      2, "calcium_mg":    50},
    "석류주스":                 {"protein_g":   0.3, "fat_g":   0.2, "carb_g":  20.7, "sugar_g":   9.9, "fiber_g":   5.8, "sodium_mg":      1, "calcium_mg":     6},
    "레드치커리":                {"protein_g":   1.4, "fat_g":   0.2, "carb_g":  17.5, "sugar_g":   8.7, "fiber_g":   1.5, "sodium_mg":     50, "calcium_mg":    41},
    "가지 1":                 {"protein_g":   1.1, "fat_g":   0.0, "carb_g":   4.4, "sugar_g":   2.3, "fiber_g":   2.7, "sodium_mg":      0, "calcium_mg":    16},
    "천연조미료":                {"protein_g":   6.8, "fat_g":   0.1, "carb_g":   9.6, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":   5906, "calcium_mg":    10},
    "꽁치":                   {"protein_g":  22.7, "fat_g":   4.7, "carb_g":   0.4, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     80, "calcium_mg":    42},
    "소불고기":                 {"protein_g":  10.3, "fat_g":  13.1, "carb_g":   6.7, "sugar_g":   3.3, "fiber_g":   0.9, "sodium_mg":    468, "calcium_mg":    18},
    "알비트":                  {"protein_g":   1.0, "fat_g":   0.1, "carb_g":   6.1, "sugar_g":   4.1, "fiber_g":   1.7, "sodium_mg":     19, "calcium_mg":     9},
    "갈치":                   {"protein_g":  18.5, "fat_g":   7.5, "carb_g":   0.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    100, "calcium_mg":    46},
    "메이플시럽":                {"protein_g":   0.0, "fat_g":   0.1, "carb_g":  67.0, "sugar_g":  60.5, "fiber_g":   0.0, "sodium_mg":     12, "calcium_mg":   102},
    "자몽":                   {"protein_g":   0.8, "fat_g":   0.1, "carb_g":   7.9, "sugar_g":   5.4, "fiber_g":   1.2, "sodium_mg":      1, "calcium_mg":    31},
    "옥수수가루":                {"protein_g":   7.3, "fat_g":   1.0, "carb_g":  83.3, "sugar_g":   0.5, "fiber_g":   1.9, "sodium_mg":      2, "calcium_mg":     5},
    "분유":                   {"protein_g":  14.0, "fat_g":  23.9, "carb_g":  56.6, "sugar_g":  47.3, "fiber_g":   0.0, "sodium_mg":    173, "calcium_mg":   680},
    "유자":                   {"protein_g":   0.9, "fat_g":   0.1, "carb_g":  12.6, "sugar_g":   4.1, "fiber_g":   3.7, "sodium_mg":      3, "calcium_mg":    36},
    "백합":                   {"protein_g":  11.7, "fat_g":   1.0, "carb_g":   3.6, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":   161},
    "커피":                   {"protein_g":   0.0, "fat_g":   0.0, "carb_g":   0.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     1},
    "민어":                   {"protein_g":  18.0, "fat_g":   0.8, "carb_g":   0.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    22},
    "마":                    {"protein_g":   1.8, "fat_g":   0.1, "carb_g":  14.1, "sugar_g":   1.0, "fiber_g":   2.4, "sodium_mg":      4, "calcium_mg":     9},
    "루꼴라":                  {"protein_g":   3.2, "fat_g":   0.4, "carb_g":   4.2, "sugar_g":   1.0, "fiber_g":   1.3, "sodium_mg":     13, "calcium_mg":   159},
    "표고":                   {"protein_g":   2.7, "fat_g":   0.4, "carb_g":   7.4, "sugar_g":   0.4, "fiber_g":   5.0, "sodium_mg":      3, "calcium_mg":     4},
    "블루베리소스 블루베리잼":         {"protein_g":   0.5, "fat_g":   0.1, "carb_g":  11.1, "sugar_g":   7.9, "fiber_g":   2.4, "sodium_mg":      0, "calcium_mg":     9},
    "팽이":                   {"protein_g":  16.1, "fat_g":   1.4, "carb_g":   2.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     70, "calcium_mg":    10},
    "말린 매생이":               {"protein_g":  20.6, "fat_g":   0.5, "carb_g":  40.6, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":   574},
    "메밀묵":                  {"protein_g":   1.1, "fat_g":   0.4, "carb_g":  11.8, "sugar_g":   0.0, "fiber_g":   1.2, "sodium_mg":    132, "calcium_mg":     8},
    "우렁":                   {"protein_g":  10.5, "fat_g":   1.4, "carb_g":   3.8, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     81, "calcium_mg":  1202},
    "겨자분말":                 {"protein_g":  18.4, "fat_g":  22.7, "carb_g":  50.0, "sugar_g":   5.5, "fiber_g":  37.8, "sodium_mg":      1, "calcium_mg":   383},
    "말린 자두":                {"protein_g":   2.5, "fat_g":   0.4, "carb_g":  62.0, "sugar_g":  34.5, "fiber_g":   6.9, "sodium_mg":      2, "calcium_mg":    48},
    "명태":                   {"protein_g":  17.5, "fat_g":   0.7, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    132, "calcium_mg":   109},
    "건조체리":                 {"protein_g":   0.3, "fat_g":   0.1, "carb_g":  31.5, "sugar_g":  21.5, "fiber_g":   1.4, "sodium_mg":      6, "calcium_mg":    68},
    "울금가루":                 {"protein_g":   7.8, "fat_g":   3.0, "carb_g":  73.2, "sugar_g":   3.7, "fiber_g":  15.2, "sodium_mg":     30, "calcium_mg":    74},
    "미더덕":                  {"protein_g":   4.3, "fat_g":   1.2, "carb_g":   4.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    40},
    "병어":                   {"protein_g":  16.4, "fat_g":   6.3, "carb_g":   0.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":    158, "calcium_mg":    22},
    "비름나물":                 {"protein_g":   2.7, "fat_g":   0.3, "carb_g":   4.0, "sugar_g":   0.3, "fiber_g":   3.4, "sodium_mg":     65, "calcium_mg":   133},
    "머위대":                  {"protein_g":   2.3, "fat_g":   0.1, "carb_g":   2.7, "sugar_g":   0.1, "fiber_g":   2.7, "sodium_mg":      2, "calcium_mg":   103},
    "전복살":                  {"protein_g":  14.3, "fat_g":   0.7, "carb_g":   4.5, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    52},
    "오미자청":                 {"protein_g":   0.1, "fat_g":   0.3, "carb_g":  55.9, "sugar_g":  50.1, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     2},
    "스위트칠리":                {"protein_g":  15.0, "fat_g":   8.2, "carb_g":  60.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":   2500, "calcium_mg":   280},
    "다슬기살":                 {"protein_g":  11.9, "fat_g":   1.2, "carb_g":   5.7, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":  1117},
    "참다래":                  {"protein_g":   0.9, "fat_g":   1.1, "carb_g":  13.3, "sugar_g":   5.5, "fiber_g":   3.0, "sodium_mg":      1, "calcium_mg":    42},
    "우동":                   {"protein_g":   3.1, "fat_g":   1.2, "carb_g":  30.5, "sugar_g":   0.3, "fiber_g":   1.8, "sodium_mg":    142, "calcium_mg":     9},
    "잎녹차":                  {"protein_g":   0.1, "fat_g":   0.0, "carb_g":   0.4, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     1},
    "마카다미아":                {"protein_g":   8.3, "fat_g":  76.7, "carb_g":  12.2, "sugar_g":   0.0, "fiber_g":   6.2, "sodium_mg":    190, "calcium_mg":    47},
    "비트가루":                 {"protein_g":   0.9, "fat_g":   0.1, "carb_g":   5.3, "sugar_g":   2.8, "fiber_g":   1.5, "sodium_mg":     20, "calcium_mg":     8},
    "쌈추":                   {"protein_g":   3.1, "fat_g":   0.2, "carb_g":   4.3, "sugar_g":   0.0, "fiber_g":   3.2, "sodium_mg":     29, "calcium_mg":   129},
    "블랙":                   {"protein_g":   1.3, "fat_g":   0.8, "carb_g":   9.6, "sugar_g":   5.0, "fiber_g":   4.2, "sodium_mg":      1, "calcium_mg":    29},
    "구기자":                  {"protein_g":   6.3, "fat_g":   1.1, "carb_g":   7.0, "sugar_g":   0.8, "fiber_g":   5.1, "sodium_mg":      2, "calcium_mg":    10},
    "올리브":                  {"protein_g":   0.0, "fat_g": 100.0, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     0},
    "삶은 스파게티":              {"protein_g":   5.0, "fat_g":   1.0, "carb_g":  15.2, "sugar_g":   2.6, "fiber_g":   1.8, "sodium_mg":    238, "calcium_mg":    18},
    "배즙 37 5":              {"protein_g":   0.2, "fat_g":   0.0, "carb_g":  10.3, "sugar_g":   8.1, "fiber_g":   0.0, "sodium_mg":      2, "calcium_mg":     2},
    "스리라차":                 {"protein_g":   1.6, "fat_g":   0.6, "carb_g":  16.2, "sugar_g":  13.7, "fiber_g":   2.1, "sodium_mg":   1519, "calcium_mg":    15},
    "산딸기":                  {"protein_g":   1.4, "fat_g":   0.2, "carb_g":  13.6, "sugar_g":   7.8, "fiber_g":   6.9, "sodium_mg":      0, "calcium_mg":    29},
    "발사믹크림":                {"protein_g":   0.7, "fat_g":   0.0, "carb_g":  44.9, "sugar_g":  37.0, "fiber_g":   0.0, "sodium_mg":     56, "calcium_mg":    23},
    "닭 육수":                 {"protein_g":   1.3, "fat_g":   0.7, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     13, "calcium_mg":    17},
    "아이스크림":                {"protein_g":   5.0, "fat_g":   7.8, "carb_g":  22.2, "sugar_g":  17.3, "fiber_g":   0.0, "sodium_mg":     70, "calcium_mg":    80},
    "리치캔":                  {"protein_g":   1.0, "fat_g":   0.1, "carb_g":  16.4, "sugar_g":   0.0, "fiber_g":   0.9, "sodium_mg":      0, "calcium_mg":     2},
    "후춧가루 강낭콩":             {"protein_g":  21.0, "fat_g":   1.4, "carb_g":  61.9, "sugar_g":   3.3, "fiber_g":  25.6, "sodium_mg":      1, "calcium_mg":    99},
    "낫토":                   {"protein_g":  17.2, "fat_g":   8.5, "carb_g":   9.9, "sugar_g":   0.4, "fiber_g":   6.9, "sodium_mg":      7, "calcium_mg":   133},
    "참마":                   {"protein_g":  17.7, "fat_g":   1.5, "carb_g":   0.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":    58},
    "피칸":                   {"protein_g":   9.5, "fat_g":  74.3, "carb_g":  13.6, "sugar_g":   4.1, "fiber_g":   9.4, "sodium_mg":    383, "calcium_mg":    72},
    "클로렐라가루":               {"protein_g":  45.3, "fat_g":   7.2, "carb_g":  25.7, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":   117},
    "과메기":                  {"protein_g":  15.1, "fat_g":   5.3, "carb_g":   0.1, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     46, "calcium_mg":    26},
    "멍게살 50":               {"protein_g":   8.7, "fat_g":   2.1, "carb_g":   4.9, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":   1300, "calcium_mg":    36},
    "곰피":                   {"protein_g":  10.0, "fat_g":   1.4, "carb_g":  51.4, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":     0},
    "민들레 15":               {"protein_g":   2.4, "fat_g":   0.4, "carb_g":   5.5, "sugar_g":   0.0, "fiber_g":   3.3, "sodium_mg":      1, "calcium_mg":   119},
    "진달래꽃 2 5":             {"protein_g":   1.0, "fat_g":   0.1, "carb_g":   6.3, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":     17, "calcium_mg":    22},
    "페이스트":                 {"protein_g":  16.5, "fat_g":   5.5, "carb_g":   2.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      0, "calcium_mg":   180},
    "해선장":                  {"protein_g":   1.6, "fat_g":   3.3, "carb_g":  48.4, "sugar_g":  44.0, "fiber_g":   1.4, "sodium_mg":   2899, "calcium_mg":    22},
    "코코넛슬라이스":              {"protein_g":   6.9, "fat_g":  64.5, "carb_g":  23.6, "sugar_g":   7.3, "fiber_g":  16.3, "sodium_mg":     37, "calcium_mg":    26},
    "대두":                   {"protein_g":  38.5, "fat_g":  21.4, "carb_g":  30.8, "sugar_g":   7.5, "fiber_g":  22.1, "sodium_mg":      4, "calcium_mg":   236},
    "도토리가루":                {"protein_g":   1.1, "fat_g":   1.1, "carb_g":  83.7, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      2, "calcium_mg":    60},
    "말린오미자":                {"protein_g":   8.5, "fat_g":  12.4, "carb_g":  62.1, "sugar_g":   9.4, "fiber_g":  30.4, "sodium_mg":      2, "calcium_mg":    53},
    "생수":                   {"protein_g":   0.0, "fat_g":   0.0, "carb_g":   0.0, "sugar_g":   0.0, "fiber_g":   0.0, "sodium_mg":      3, "calcium_mg":     1},
    "코코아":                  {"protein_g":  22.9, "fat_g":  20.1, "carb_g":  43.6, "sugar_g":   0.5, "fiber_g":   0.0, "sodium_mg":     24, "calcium_mg":   161},
    "흰강낭콩":                 {"protein_g":   8.8, "fat_g":   0.9, "carb_g":  32.4, "sugar_g":   1.6, "fiber_g":  14.1, "sodium_mg":      0, "calcium_mg":    49},
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

# [FIX] AI 추정에 실패한 재료명을 기억해 둔다.
# 기존에는 실패를 기록하지 않아서, 검색할 때마다 '파인애플'·'케일'처럼
# 똑같이 실패하는 재료를 몇 번이고 다시 물어봤다. 한도가 찬 상태에서는
# 이 재시도가 오히려 한도를 더 태워서 다른 기능(쉽게보기 등)까지 죽였다.
# 서버가 재시작되면 비워지므로(= 한도 회복 후 자동 재시도) 영구 포기는 아니다.
_FAILED_KEYS: set = set()


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
    # 이미 값이 있거나, 직전에 실패한 재료는 다시 묻지 않는다
    keys = [k for k in keys if _lookup(k) is None and k not in _FAILED_KEYS]
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

        # [FIX] response_mime_type="application/json"만 지정하면 모델이 최상위를
        # 객체로 감싸서 {"result": [...]} 형태로 돌려주는 경우가 있다.
        # 그럴 때 통째로 버리지 말고 안에 든 배열을 꺼내 쓴다.
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break

        if not isinstance(data, list):
            print(f"[nutrition_service] AI 응답이 배열이 아님({provider}), 원본: {str(data)[:300]}")
            _FAILED_KEYS.update(keys)
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
        # 이번에 값을 못 받은 키는 실패로 기록해 반복 호출을 막는다
        _FAILED_KEYS.update(k for k in keys if k not in filled)
        print(f"[nutrition_service] AI 영양성분 배치 완료({provider}): {len(filled)}/{len(keys)}건 성공")
        return filled

    except Exception as e:
        # [FIX] traceback 전체 출력은 429가 수십 번 날 때 로그를 덮어버려
        # 정작 봐야 할 줄을 못 찾게 만든다. 한 줄 요약만 남긴다.
        _FAILED_KEYS.update(keys)
        print(f"[nutrition_service] AI 영양성분 배치 오류 ({type(e).__name__}): {str(e)[:200]}")
        return {}


async def get_nutrition_for_ingredient(standard_nm: str, amount_g: float,
                                       allow_ai: bool = True) -> Dict:
    """allow_ai=False면 로컬표·캐시에만 의존하고 AI는 절대 호출하지 않는다.

    [FIX] 추천 목록(/recommend)은 레시피 50개 × 재료 수만큼 이 함수를 부른다.
    그런데 추천 점수에 쓰이는 열량·단백질·나트륨은 식약처가 레시피 단위로
    직접 주는 값(INFO_ENG 등)이라, 재료별 AI 추정이 점수에 전혀 반영되지 않는다.
    즉 쓰이지도 않는 값을 위해 AI 호출을 40번 넘게 소모하고, 그 때문에 정작
    필요한 '쉽게 보기'·조리시간 분석이 할당량 부족으로 실패했다.
    목록 단계에서는 allow_ai=False로 호출해 할당량을 상세 화면에 남겨둔다.
    """
    if not standard_nm or amount_g <= 0:
        return _empty()

    key  = _normalize_name(standard_nm)
    base = _lookup(key)

    if base is not None:
        return _scale(key, base, amount_g, "nutrition_local" if key in LOCAL_NUTRITION_100G else "nutrition_ai")

    if not allow_ai:
        return _empty()

    # [안전장치] recipe_service.py 의 배치 사전조회를 거치지 않은 경우를 대비
    await estimate_nutrition_batch([key])
    base = _lookup(key)
    if base is not None:
        return _scale(key, base, amount_g, "nutrition_ai")

    print(f"[nutrition_service] 최종 실패 — 0으로 표시됨: '{standard_nm}' (정규화: '{key}')")
    return _empty()