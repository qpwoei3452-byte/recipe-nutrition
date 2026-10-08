from typing import List, Dict, Optional

# [FIX] 사용자 테스트 기간 동안 모든 부가 부스트를 일괄 무력화.
# 종료 후 False로 되돌리면 원래 로직 복원됨.
USER_TEST_MODE = False   # ← True에서 False로 변경 (냉장고 필터 활성화)

PRESET_WEIGHTS = {
    "가성비":   {"price": 0.40, "protein": 0.18, "calorie": 0.10, "sodium": 0.07, "time": 0.25},
    "고단백":   {"price": 0.18, "protein": 0.42, "calorie": 0.15, "sodium": 0.10, "time": 0.15},
    "저칼로리": {"price": 0.15, "protein": 0.18, "calorie": 0.40, "sodium": 0.15, "time": 0.12},
    "저염":     {"price": 0.15, "protein": 0.20, "calorie": 0.15, "sodium": 0.40, "time": 0.10},
    "기본":     {"price": 0.25, "protein": 0.22, "calorie": 0.18, "sodium": 0.15, "time": 0.20},
}

TIME_SLOT_WEIGHTS = {
    "아침": {"price": 0.15, "protein": 0.10, "calorie": 0.30, "sodium": 0.10, "time": 0.35},
    "점심": {"price": 0.25, "protein": 0.25, "calorie": 0.20, "sodium": 0.15, "time": 0.15},
    "저녁": {"price": 0.25, "protein": 0.35, "calorie": 0.15, "sodium": 0.15, "time": 0.10},
    "야식": {"price": 0.10, "protein": 0.05, "calorie": 0.40, "sodium": 0.25, "time": 0.20},
}

POPULAR_FOODS: Dict[str, float] = {
    "김치찌개": 1.0, "된장찌개": 1.0, "비빔밥":   1.0,
    "불고기":   1.0, "삼겹살":   1.0, "라면":     1.0,
    "계란":     0.9, "김밥":     1.0, "제육볶음": 1.0,
    "닭볶음탕": 0.85, "순두부찌개": 0.85, "부대찌개": 0.85,
    "육개장":   0.85, "삼계탕":    0.85, "갈비탕":   0.80,
    "갈비찜":   0.80, "잡채":      0.80, "떡볶이":   0.80,
    "파전":     0.75, "감자탕":    0.75, "설렁탕":   0.75,
    "닭갈비":   0.75, "돼지국밥":  0.75, "수육":     0.70,
    "볶음밥":   0.70, "된장국":    0.70, "미역국":   0.70,
    "콩나물국": 0.65, "두부조림":  0.65, "멸치볶음": 0.65,
    "김치볶음": 0.65, "소불고기":  0.65, "어묵볶음": 0.60,
    "계란말이": 0.60, "떡국":      0.60, "순대국":   0.60,
    "해장국":   0.60,
}
# [FIX] 0.28 → 0.06
# 사용자 가중치로 계산한 기본 점수는 0~1(실제로는 0.2~0.8) 범위인데,
# 인기 메뉴면 +0.28, 아니면 ×0.78 감점이 붙어 두 집단 사이에 0.3~0.4점
# 차이가 벌어졌다. 사용자가 슬라이더를 어떻게 움직여도 이 차이를 뒤집기
# 어려워, "개인 맞춤형"이라는 기능이 사실상 무력화돼 있었다.
#
# 실제 로그 예시:
#   부대된장찌개      기본=1.000 인기=0.28 → 1.000
#   사과 새우 북엇국   기본=0.784 인기=0.00 → 0.612   ← 기본 점수가 높은데 밀림
#
# 50건 실데이터로 측정한 변화 (가성비·단백질·저염·빠른조리·저칼로리 5개 프로필):
#   프로필 간 Top10 중복도 0.485 → 0.263   (낮을수록 개인화가 작동)
#   Top10 내 인기메뉴 비중   60% → 18%
#   점수 1.000 포화 레시피   6개 → 0개      (순위 구분이 가능해짐)
#
# 인기도를 버린 것은 아니다. POPULAR_FOODS 목록과 _popularity_bonus()는
# 그대로 두고, 영향력만 "비슷한 점수끼리 순서를 가르는" 수준으로 낮췄다.
POPULARITY_BONUS = 0.06

WEIGHTS     = PRESET_WEIGHTS
WEIGHT_KEYS = ("price", "protein", "calorie", "sodium", "time")


def _normalize_weights(w: Dict[str, float]) -> Dict[str, float]:
    try:
        vals = {k: max(0.0, float(w.get(k, 0))) for k in WEIGHT_KEYS}
    except (TypeError, ValueError):
        return dict(PRESET_WEIGHTS["기본"])
    total = sum(vals.values())
    if total <= 0:
        return dict(PRESET_WEIGHTS["기본"])
    return {k: round(v / total, 4) for k, v in vals.items()}


def resolve_weights(
    mode: str = "기본",
    user_weights: Optional[Dict[str, float]] = None,
    w_price:   Optional[float] = None,
    w_protein: Optional[float] = None,
    w_calorie: Optional[float] = None,
    w_sodium:  Optional[float] = None,
    w_time:    Optional[float] = None,
    time_slot: Optional[str]   = None,
) -> Dict[str, float]:
    if user_weights:
        return _normalize_weights(user_weights)
    custom = [w_price, w_protein, w_calorie, w_sodium, w_time]
    if any(v is not None for v in custom):
        raw = {
            "price":   max(w_price   or 0, 0),
            "protein": max(w_protein or 0, 0),
            "calorie": max(w_calorie or 0, 0),
            "sodium":  max(w_sodium  or 0, 0),
            "time":    max(w_time    or 0, 0),
        }
        total = sum(raw.values()) or 1
        return {k: round(v / total, 4) for k, v in raw.items()}
    if time_slot and time_slot in TIME_SLOT_WEIGHTS:
        print(f"[resolve_weights] 시간대 자동 가중치: {time_slot}")
        return dict(TIME_SLOT_WEIGHTS[time_slot])
    base = PRESET_WEIGHTS.get(mode, PRESET_WEIGHTS["기본"]).copy()
    base.setdefault("sodium", 0)
    return base


def blend_with_log(
    base_weights: Dict[str, float],
    history_recipes: Optional[List[Dict]] = None,
    alpha: float = 0.25,
) -> Dict[str, float]:
    if not history_recipes or len(history_recipes) < 3:
        return dict(base_weights)
    sums = {k: 0.0 for k in WEIGHT_KEYS}
    n = 0
    for r in history_recipes:
        sc = r.get("_scores")
        if not sc:
            continue
        for k in WEIGHT_KEYS:
            sums[k] += sc.get(k, 0)
        n += 1
    if n == 0:
        return dict(base_weights)
    avg = {k: sums[k] / n for k in WEIGHT_KEYS}
    total_avg = sum(avg.values()) or 1
    log_signal = {k: avg[k] / total_avg for k in WEIGHT_KEYS}
    blended = {k: (1 - alpha) * base_weights.get(k, 0) + alpha * log_signal[k] for k in WEIGHT_KEYS}
    total = sum(blended.values()) or 1
    return {k: round(blended[k] / total, 4) for k in WEIGHT_KEYS}


def normalize_scores(recipes: List[Dict]) -> List[Dict]:
    if not recipes:
        return recipes

    # [FIX] 가격을 못 구해 0원인 레시피가 1 - 0/max = 1.0 으로 '가장 저렴함'
    # 만점을 받아 가성비 모드 1위로 올라가던 버그.
    # 가격 미상은 "싸다"가 아니라 "모른다"이므로, 값이 있는 레시피들의
    # 중앙값으로 대체해 중립적으로 취급한다.
    known_costs = sorted(c for c in
                         (r.get("price_total_krw", 0) or 0 for r in recipes) if c > 0)
    if known_costs:
        mid = len(known_costs) // 2
        unknown_cost = (known_costs[mid] if len(known_costs) % 2
                        else (known_costs[mid - 1] + known_costs[mid]) / 2)
    else:
        unknown_cost = 0.0
    for r in recipes:
        if not (r.get("price_total_krw", 0) or 0) > 0:
            r["price_estimated"] = True      # 프론트에서 '가격 정보 없음' 표시용

    # [FIX] 기존에는 max만 써서 `1 - x/max` 로 계산했다. 두 가지 문제가 있었다.
    #   (1) 후보가 1개면 자기 자신이 최댓값이라 모든 점수가 0이 된다
    #   (2) 후보들의 값이 비슷하면 점수가 전부 1 근처에 몰려 변별력이 사라진다
    # 표준적인 min-max 정규화로 바꿔, 후보 집합 안에서의 상대 위치를 반영한다.
    # 값이 모두 같거나 후보가 1개면 0.5(중립)를 준다.
    def _collect(getter):
        return [getter(r) for r in recipes]

    def _winsorize(values, p=0.05):
        """[FIX] 이상값 1건이 정규화 전체를 왜곡하는 문제를 막는다.

        식약처 데이터에 `표고버섯 청경채국` 나트륨 2,441mg 같은 입력 오류가
        있다(재료는 국간장 5g뿐이라 실제로는 300mg 수준). 이 값이 min-max의
        최댓값이 되면 나머지 레시피의 나트륨 점수가 모두 1 근처로 몰려
        저염 가중치가 사실상 작동하지 않는다.

          이상값 포함: 50건 중 40건이 0.8 이상 (1사분위 0.846)
          이상값 제외: 49건 중 28건이 0.8 이상 (1사분위 0.637)

        원본 데이터를 고치는 대신, 상·하위 5%를 해당 분위값으로 자르는
        윈저화(winsorizing)를 적용한다. 통계에서 쓰는 표준 기법이고
        값을 임의로 바꾸지 않으므로 근거가 분명하다.
        """
        if len(values) < 10:          # 후보가 적으면 분위수가 의미 없다
            return values
        ordered = sorted(values)
        lo = ordered[int(len(ordered) * p)]
        hi = ordered[min(len(ordered) - 1, int(len(ordered) * (1 - p)))]
        return [min(max(v, lo), hi) for v in values]

    def _mk(values, higher_is_better: bool):
        values = _winsorize(values)
        lo, hi = min(values), max(values)
        span = hi - lo
        if span <= 0:                 # 전부 같은 값 / 후보 1개 → 중립
            return [0.5] * len(values)
        if higher_is_better:
            return [round((v - lo) / span, 4) for v in values]
        return [round((hi - v) / span, 4) for v in values]

    costs   = [(r.get("price_total_krw", 0) or 0) or unknown_cost for r in recipes]
    prots   = [r.get("nutrition_total", {}).get("protein_g", 0) or 0 for r in recipes]
    cals    = [r.get("nutrition_total", {}).get("energy_kcal", 0) or 0 for r in recipes]
    sodiums = [r.get("nutrition_total", {}).get("sodium_mg", 0) or 0 for r in recipes]
    times   = [r.get("cook_time_min", 30) or 30 for r in recipes]

    s_price   = _mk(costs,   higher_is_better=False)   # 쌀수록 좋음
    s_protein = _mk(prots,   higher_is_better=True)    # 많을수록 좋음
    s_calorie = _mk(cals,    higher_is_better=False)   # 낮을수록 좋음
    s_sodium  = _mk(sodiums, higher_is_better=False)   # 낮을수록 좋음
    s_time    = _mk(times,   higher_is_better=False)   # 짧을수록 좋음

    for i, r in enumerate(recipes):
        r["_scores"] = {
            "price":   s_price[i],
            "protein": s_protein[i],
            "calorie": s_calorie[i],
            "sodium":  s_sodium[i],
            "time":    s_time[i],
        }
        print(f"[normalize_scores] {r.get('name','?')}: "
              f"가격={costs[i]} 칼로리={cals[i]} 단백질={prots[i]} "
              f"나트륨={sodiums[i]} 시간={times[i]}분 → _scores={r['_scores']}")
    return recipes


def _ingredient_set(recipe: Dict) -> set:
    ings = recipe.get("ingredients", []) or []
    names = set()
    for ing in ings:
        nm = (
            ing.get("standard_nm")
            or ing.get("standard_name")
            or ing.get("name")
            or ing.get("raw_name")
            or ""
        )
        if nm:
            names.add(str(nm).strip())
    return names


SPELLING_VARIANTS = [
    ("게란", "계란"), ("달걀", "계란"),
    ("닭도리탕", "닭볶음탕"), ("북엇", "북어"), ("야채", "채소"),
]


def _normalize_name(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    for a, b in SPELLING_VARIANTS:
        t = t.replace(a, b)
    return t


def _longest_common_substr(s1: str, s2: str) -> str:
    if not s1 or not s2:
        return ""
    m, n = len(s1), len(s2)
    prev = [0] * (n + 1)
    best = 0
    end = 0
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
                    end = i
        prev = curr
    return s1[end - best:end] if best > 0 else ""


def _name_token_similarity(name_a: str, name_b: str) -> float:
    a = _normalize_name(name_a)
    b = _normalize_name(name_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    SUFFIX_WORDS = {
        "구이", "볶음", "찌개", "조림", "무침", "튀김",
        "전골", "말이", "샐러드", "수프", "비빔", "덮밥",
        "탕", "국", "전", "찜", "죽", "면",
        "볶음밥", "주먹밥", "비빔밥", "볶음면", "비빔면",
    }
    from_a = _longest_common_substr(a, b)
    if len(from_a) >= 2:
        if from_a in SUFFIX_WORDS:
            return 0.25
        ratio = len(from_a) / max(2, min(len(a), len(b)))
        if ratio >= 0.5:
            return min(0.85, 0.5 + ratio * 0.4)
    a_words = [w for w in a.replace(",", " ").split() if len(w) >= 2]
    b_words = [w for w in b.replace(",", " ").split() if len(w) >= 2]
    if not a_words or not b_words:
        return 0.0
    hits = sum(1 for w in a_words if any(w in bw or bw in w for bw in b_words))
    ratio = hits / max(len(a_words), len(b_words))
    if ratio >= 0.7:
        return 0.8
    if ratio >= 0.4:
        return 0.5
    return 0.0


def name_similarity(recipe_name: str, history: List[str]) -> float:
    if not history:
        return 0.0
    name_lower = _normalize_name(recipe_name.strip())
    max_sim = 0.0
    for h in history:
        h_norm = _normalize_name(h.strip())
        if not h_norm:
            continue
        if h_norm in name_lower or name_lower in h_norm:
            max_sim = max(max_sim, 0.95)
            continue
        h_words = [w for w in h_norm.replace(",", " ").split() if len(w) >= 2]
        if not h_words:
            continue
        hits = sum(1 for w in h_words if w in name_lower)
        ratio = hits / len(h_words)
        if ratio >= 0.7:
            max_sim = max(max_sim, 0.85)
        elif ratio >= 0.4:
            max_sim = max(max_sim, 0.55)
    return round(min(max_sim, 1.0), 4)


def apply_penalty(base_score: float, similarity: float) -> float:
    return round(base_score * (1.0 - similarity * 0.8), 4)


def pair_similarity(a: Dict, b: Dict) -> float:
    if _normalize_name(a.get("name", "")) == _normalize_name(b.get("name", "")) and a.get("name"):
        return 1.0
    a_ings = _ingredient_set(a)
    b_ings = _ingredient_set(b)
    if a_ings and b_ings:
        inter = len(a_ings & b_ings)
        union = len(a_ings | b_ings)
        jaccard = inter / union if union else 0.0
    else:
        jaccard = 0.0
    cat_bonus = 0.15 if (a.get("category") and a.get("category") == b.get("category")) else 0.0
    ing_sim = min(1.0, jaccard * 0.8 + cat_bonus)
    name_sim = _name_token_similarity(a.get("name", ""), b.get("name", ""))
    return round(min(1.0, max(ing_sim, name_sim)), 4)


def calc_similarity(recipe: Dict, others: Optional[List[Dict]]) -> float:
    if not others:
        return 0.0
    return round(max((pair_similarity(recipe, o) for o in others), default=0.0), 4)


def mmr_rerank(
    recipes: List[Dict],
    history_recipes: Optional[List[Dict]] = None,
    lambda_: float = 0.7,
    top_n: int = 20,
) -> List[Dict]:
    if not recipes:
        return []
    if top_n <= 0:          # [FIX] top_n=0이면 결과가 항상 빈 배열이 되는 버그 방지
        top_n = 20
    history = history_recipes or []
    candidates = list(recipes)
    selected: List[Dict] = []
    while candidates and len(selected) < top_n:
        best, best_mmr = None, None
        for r in candidates:
            relevance = r.get("base_score", 0.0)
            compare_set = selected + history
            max_sim = calc_similarity(r, compare_set) if compare_set else 0.0
            mmr = lambda_ * relevance - (1 - lambda_) * max_sim
            if best_mmr is None or mmr > best_mmr:
                best_mmr, best = mmr, r
        best["mmr_score"] = round(best_mmr, 4)
        best["diversity_sim"] = calc_similarity(best, selected + history) if (selected or history) else 0.0
        selected.append(best)
        candidates.remove(best)
    return selected


def calc_score(recipe: Dict, weights: Dict[str, float]) -> float:
    s = recipe.get("_scores", {})
    return round(
        s.get("price",   0) * weights.get("price",   0) +
        s.get("protein", 0) * weights.get("protein", 0) +
        s.get("calorie", 0) * weights.get("calorie", 0) +
        s.get("sodium",  0) * weights.get("sodium",  0) +
        s.get("time",    0) * weights.get("time",    0),
        4
    )


def build_reason(recipe: Dict, weights: Dict[str, float]) -> str:
    s  = recipe.get("_scores", {})
    nt = recipe.get("nutrition_total", {})
    candidates = []
    if s.get("price",   0) >= 0.65:
        cost = int(recipe.get("price_total_krw", 0))
        candidates.append(("price",   f"재료비가 저렴해요 (약 {cost:,}원)"))
    if s.get("protein", 0) >= 0.65:
        prot = nt.get("protein_g", 0)
        candidates.append(("protein", f"단백질 함량이 높아요 ({prot:.1f}g)"))
    if s.get("calorie", 0) >= 0.65:
        cal = nt.get("energy_kcal", 0)
        candidates.append(("calorie", f"칼로리가 낮아요 ({cal:.0f}kcal)"))
    if s.get("sodium",  0) >= 0.65:
        sod = nt.get("sodium_mg", 0)
        candidates.append(("sodium",  f"나트륨이 낮아요 ({sod:.0f}mg)"))
    if s.get("time",    0) >= 0.65:
        t = recipe.get("cook_time_min", 0)
        candidates.append(("time",    f"조리시간이 짧아요 ({t}분)"))
    if not candidates:
        return "가격, 영양, 조리시간 균형이 좋아요"
    candidates.sort(key=lambda c: weights.get(c[0], 0), reverse=True)
    return " · ".join(text for _, text in candidates)


def _popularity_bonus(recipe_name: str) -> float:
    name_n = _normalize_name(recipe_name)
    best = 0.0
    for keyword, weight in POPULAR_FOODS.items():
        kw_n = _normalize_name(keyword)
        if kw_n in name_n:
            ratio = len(kw_n) / max(len(name_n), 1)
            if ratio >= 0.35:
                best = max(best, weight)
    return round(best * POPULARITY_BONUS, 4)


# [FIX] 양념·기본 재료는 "집에 당연히 있다"고 보고 냉장고 매칭에서 제외한다.
PANTRY_STAPLES = {
    "소금", "설탕", "간장", "식초", "고추장", "된장", "쌈장", "참기름", "들기름",
    "식용유", "올리브유", "후추", "후춧가루", "고춧가루", "물", "맛술", "청주",
    "마늘", "대파", "생강", "깨", "참깨", "물엿", "올리고당", "전분", "녹말가루",
}


def _ingredient_matches(ing_norm: str, fridge_norm: str) -> bool:
    """[FIX] 기존에는 양방향 부분 문자열(a in b or b in a)이라
    '파'를 입력하면 대파·쪽파·파프리카·파슬리가 전부 걸려 필터가
    사실상 무력화됐다. 1~2글자 입력은 완전일치만 인정한다."""
    if not ing_norm or not fridge_norm:
        return False
    if len(fridge_norm) <= 2:
        return ing_norm == fridge_norm
    return fridge_norm in ing_norm or ing_norm in fridge_norm


def _main_ingredients(recipe: Dict) -> set:
    """양념류를 뺀 '주재료' 집합."""
    return {n for n in (_normalize_name(i) for i in _ingredient_set(recipe))
            if n and n not in PANTRY_STAPLES}


def _fridge_coverage(recipe: Dict, fridge_ingredients: List[str]) -> float:
    """레시피 주재료 중 내 냉장고로 커버되는 비율 (0.0 ~ 1.0)."""
    mains = _main_ingredients(recipe)
    if not mains:
        return 0.0
    fridge_norm = [_normalize_name(f.strip()) for f in fridge_ingredients]
    fridge_norm = [f for f in fridge_norm if f]
    if not fridge_norm:
        return 0.0
    covered = sum(1 for m in mains if any(_ingredient_matches(m, f) for f in fridge_norm))
    return round(covered / len(mains), 4)


def _fridge_match_score(recipe: Dict, fridge_ingredients: List[str]) -> float:
    """점수 가산용: 내 재료가 몇 개나 쓰이는지 (최대 +0.20)."""
    if not fridge_ingredients:
        return 0.0
    mains = _main_ingredients(recipe)
    fridge_norm = [_normalize_name(f.strip()) for f in fridge_ingredients]
    matches = sum(1 for f in fridge_norm if f and any(_ingredient_matches(m, f) for m in mains))
    return round(min(matches * 0.05, 0.20), 4)


def _rating_adjustment(recipe_name: str, liked_names: List[str], disliked_names: List[str]) -> float:
    adj = 0.0
    name_n = _normalize_name(recipe_name)
    for liked in liked_names:
        sim = _name_token_similarity(name_n, _normalize_name(liked))
        if sim >= 0.7:
            adj += 0.12; break
        elif sim >= 0.4:
            adj += 0.06
    for disliked in disliked_names:
        sim = _name_token_similarity(name_n, _normalize_name(disliked))
        if sim >= 0.7:
            adj -= 0.15; break
        elif sim >= 0.4:
            adj -= 0.08
    return round(max(-0.15, min(0.12, adj)), 4)


def recommend(
    recipes:               List[Dict],
    mode:                  str                        = "기본",
    top_n:                 int                        = 20,
    user_weights:          Optional[Dict[str, float]] = None,
    w_price:               Optional[float]            = None,
    w_protein:             Optional[float]            = None,
    w_calorie:             Optional[float]            = None,
    w_sodium:              Optional[float]            = None,
    w_time:                Optional[float]            = None,
    user_history:          List[str]                  = [],
    history_recipes:       Optional[List[Dict]]       = None,
    similarity_map:        Dict                       = {},
    mmr_lambda:            float                      = 0.7,
    time_slot:             Optional[str]              = None,
    fridge_ingredients:    List[str]                  = [],
    liked_recipe_names:    List[str]                  = [],
    disliked_recipe_names: List[str]                  = [],
    fridge_only:           bool                       = False,
    fridge_mode:           str                        = "boost",
) -> List[Dict]:
    if not recipes:
        return []

    # fridge_mode: boost | any | mostly
    if fridge_only and fridge_mode == "boost":
        fridge_mode = "any"          # 구버전 프론트 호환

    if fridge_ingredients and fridge_mode != "boost" and not USER_TEST_MODE:
        threshold = 0.7 if fridge_mode == "mostly" else 0.0
        filtered = [r for r in recipes
                    if _fridge_coverage(r, fridge_ingredients) > threshold]
        print(f"[recommend] 냉장고 필터({fridge_mode}, 기준 {threshold}): "
              f"{len(recipes)}개 → {len(filtered)}개")
        recipes = filtered
        if not recipes:
            return []

    recipes = normalize_scores(recipes)

    base_weights = resolve_weights(
        mode, user_weights,
        w_price, w_protein, w_calorie, w_sodium, w_time,
        time_slot=time_slot,
    )
    weights = blend_with_log(base_weights, history_recipes)

    has_history         = history_recipes is not None and len(history_recipes) > 0
    personalized_by_log = history_recipes is not None and len(history_recipes) >= 3

    for r in recipes:
        base = calc_score(r, weights)
        name = r.get("name", "")

        ai_sim   = float(similarity_map.get(name, 0.0)) if similarity_map else 0.0
        name_sim = name_similarity(name, user_history)
        sim      = max(ai_sim, name_sim)
        penalized = apply_penalty(base, sim)

        if USER_TEST_MODE:
            pop_bonus    = 0.0
            fridge_bonus = 0.0
            rating_adj   = 0.0
            final_score  = round(min(1.0, max(0.0, penalized)), 4)
        else:
            pop_bonus    = _popularity_bonus(name)
            fridge_bonus = _fridge_match_score(r, fridge_ingredients)
            rating_adj   = _rating_adjustment(name, liked_recipe_names, disliked_recipe_names)
            final_score  = round(min(1.0, max(0.0, penalized + pop_bonus + fridge_bonus + rating_adj)), 4)

        r["base_score"]          = final_score
        r["score"]               = final_score
        r["similarity_score"]    = sim
        r["popularity_bonus"]    = pop_bonus
        r["fridge_bonus"]        = fridge_bonus
        r["rating_adjustment"]   = rating_adj
        r["reason"]              = build_reason(r, weights)
        r["mode"]                = mode
        r["weights"]             = weights
        r["personalized_by_log"] = personalized_by_log
        r["time_slot"]           = time_slot or ""

        extra_tags = []
        if pop_bonus >= 0.10:
            extra_tags.append("🔥 인기 음식")
        if fridge_bonus >= 0.05:
            extra_tags.append("🧊 냉장고 재료 활용")
        if rating_adj > 0:
            extra_tags.append("⭐ 내 취향")
        if rating_adj < 0:
            extra_tags.append("👎 비선호 유사")
        if sim >= 0.6:
            extra_tags.append("⚠️ 최근에 드신 음식과 비슷해요")
        elif sim >= 0.3:
            extra_tags.append("🔄 비슷한 재료 포함")
        if extra_tags:
            r["reason"] = " · ".join(extra_tags) + " · " + r["reason"]

        print(f"[recommend] {name}: 기본={base:.3f} 인기={pop_bonus:.2f} "
              f"냉장고={fridge_bonus:.2f} 별점={rating_adj:+.2f} → {final_score:.3f}")

    ranked = mmr_rerank(
        recipes,
        history_recipes=history_recipes if has_history else None,
        lambda_=mmr_lambda,
        top_n=top_n,
    )
    for r in ranked:
        r["similarity_score"] = r.get("diversity_sim", r.get("similarity_score", 0.0))
        r["mmr_lambda"]       = mmr_lambda

    return ranked