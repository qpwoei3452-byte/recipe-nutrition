from typing import List, Dict, Optional

# [FIX] 사용자 테스트 기간 동안 모든 부가 부스트를 일괄 무력화.
# 종료 후 False로 되돌리면 원래 로직 복원됨.
USER_TEST_MODE = True

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
POPULARITY_BONUS = 0.28

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
    max_cost    = max(r.get("price_total_krw", 0) or 0 for r in recipes) or 1
    max_protein = max(r.get("nutrition_total", {}).get("protein_g", 0) or 0 for r in recipes) or 1
    max_cal     = max(r.get("nutrition_total", {}).get("energy_kcal", 0) or 0 for r in recipes) or 1
    max_sodium  = max(r.get("nutrition_total", {}).get("sodium_mg", 0) or 0 for r in recipes) or 1
    max_time    = max(r.get("cook_time_min", 30) or 30 for r in recipes) or 1
    for r in recipes:
        nt     = r.get("nutrition_total", {})
        cost   = r.get("price_total_krw", 0) or 0
        prot   = nt.get("protein_g", 0) or 0
        cal    = nt.get("energy_kcal", 0) or 0
        sodium = nt.get("sodium_mg", 0) or 0
        time   = r.get("cook_time_min", 30) or 30
        r["_scores"] = {
            "price":   round(1 - cost   / max_cost,   4),
            "protein": round(prot       / max_protein, 4),
            "calorie": round(1 - cal    / max_cal,     4),
            "sodium":  round(1 - sodium / max_sodium,  4),
            "time":    round(1 - time   / max_time,    4),
        }
        print(f"[normalize_scores] {r.get('name','?')}: "
              f"가격={cost}/{max_cost} 칼로리={cal}/{max_cal} "
              f"단백질={prot}/{max_protein} 나트륨={sodium}/{max_sodium} "
              f"→ _scores={r['_scores']}")
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
            # 키워드가 레시피명의 35% 이상 차지해야 유효 매칭
            # (예: "해장국"이 "저염탄장으로맛을낸황태해장국"에서 21% → 보너스 없음)
            ratio = len(kw_n) / max(len(name_n), 1)
            if ratio >= 0.35:
                best = max(best, weight)
    return round(best * POPULARITY_BONUS, 4)


def _fridge_match_score(recipe: Dict, fridge_ingredients: List[str]) -> float:
    if not fridge_ingredients:
        return 0.0
    ing_set_norm = {_normalize_name(i) for i in _ingredient_set(recipe)}
    matches = 0
    for fi in fridge_ingredients:
        fi_n = _normalize_name(fi.strip())
        if not fi_n:
            continue
        if any(fi_n in ing or ing in fi_n for ing in ing_set_norm if ing):
            matches += 1
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
) -> List[Dict]:
    if not recipes:
        return []

    if fridge_ingredients and fridge_only and not USER_TEST_MODE:
        recipes = [r for r in recipes if _fridge_match_score(r, fridge_ingredients) > 0]
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
            if pop_bonus == 0.0:
                penalized = round(penalized * 0.78, 4)
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
