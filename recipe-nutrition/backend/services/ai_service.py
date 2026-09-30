# ================================================================
# ai_service.py
# ================================================================

from services import llm_service


# ── 기능 1: 카드 클릭 시 단일 레시피 분석 ──────────────────────
async def analyze_recipe(
    recipe_name:  str,
    manual_steps: list[str],
    user_history: list[str] = [],
) -> dict:
    steps      = [s.strip() for s in manual_steps if s and len(s.strip()) > 3]
    steps_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(steps)])

    history_text = (
        "최근 먹은 음식: " + ", ".join(user_history)
        if user_history
        else "최근 먹은 음식: 없음"
    )

    step_section = (
        f"[조리 단계]\n{steps_text}"
        if steps_text
        else "[조리 단계]\n정보 없음 (레시피명으로 추정해주세요)"
    )

    prompt = f"""아래 레시피를 분석하고 JSON 형식으로만 답하세요.
마크다운, 설명, 추가 텍스트 없이 JSON만 반환하세요.

[레시피명]
{recipe_name}

{step_section}

[사용자 식단 기록]
{history_text}

[분석 요청]
1. cook_time_min: 실제 조리 시간(분). 숙성/재우기/냉장 대기 시간은 제외.
2. cook_time_confidence: "high" / "medium" / "low"
3. recommendation_reason: 추천 이유 20자 이내
4. similarity_score: 최근 먹은 음식과 유사도 0.0~1.0 (기록 없으면 0.0)
5. similarity_reason: 유사도 판단 근거 한 줄

반드시 아래 JSON만 반환:
{{
  "cook_time_min": 숫자,
  "cook_time_confidence": "high 또는 medium 또는 low",
  "recommendation_reason": "문자열",
  "similarity_score": 숫자,
  "similarity_reason": "문자열"
}}"""

    try:
        print(f"[ai_service] 단일 분석 시작: {recipe_name}")
        data, provider = await llm_service.generate_json(
            prompt, temperature=0.3, max_tokens=300, as_object=True
        )
        print(f"[ai_service] 단일 완료({provider}): {recipe_name} → {data.get('cook_time_min')}분")
        # [FIX] Groq로 응답했을 때도 "Gemini AI 분석"이라고 고정 표시되던 문제.
        # 실제로 응답한 provider를 반영해서 표시(내부 로그/데이터용, UI에 굳이
        # provider 이름을 노출하지 않아도 됨 — 필요하면 프론트에서 활용 가능).
        label = "AI 분석" if steps else "AI 추정"
        data["cook_time_source"] = f"{'Gemini' if provider == 'gemini' else 'Groq'} {label}"
        return data

    except Exception as e:
        print(f"[ai_service] 단일 오류 ({type(e).__name__}): {e}")
        return {
            "cook_time_min":         20,
            "cook_time_confidence":  "low",
            "cook_time_source":      "오류로 인한 기본값",
            "recommendation_reason": "분석 중 오류 발생",
            "similarity_score":      0.0,
            "similarity_reason":     "분석 불가",
        }


# ── 기능 2: 검색 시 레시피 전체 유사도 일괄 계산 ───────────────
async def analyze_similarity_batch(
    recipe_names: list[str],
    user_history: list[str],
) -> dict[str, float]:
    """
    레시피 목록 전체의 유사도를 AI가 한 번에 계산.
    맛·식감·주재료·조리법을 종합적으로 판단.
    """
    if not user_history:
        return {name: 0.0 for name in recipe_names}

    history_str = ", ".join(user_history)
    names_str   = "\n".join([f"- {name}" for name in recipe_names])

    prompt = f"""사용자가 최근 먹은 음식과 아래 레시피 목록의 유사도를 분석하세요.
JSON 형식으로만 답하세요. 마크다운, 설명 없이 JSON만 반환하세요.

[사용자가 최근 먹은 음식]
{history_str}

[추천 레시피 목록]
{names_str}

[유사도 판단 기준 - 반드시 아래 기준으로 엄격하게 판단]
- 레시피명이 최근 먹은 음식 목록에 정확히 포함되면 → 0.95
- 주재료가 완전히 같은 음식 (예: 새우전복찜 ↔ 새우찜) → 0.8~0.9
- 같은 종류의 조리법 + 비슷한 재료 (예: 국물 요리끼리) → 0.5~0.7
- 재료 일부만 겹침 → 0.2~0.4
- 완전히 다른 음식 → 0.0~0.1

[중요] 최근 먹은 음식과 이름이 동일하거나 매우 유사한 레시피는 반드시 0.8 이상으로 설정할 것

반드시 아래 JSON 형식으로만 반환 (레시피명을 key로):
{{
  "레시피명1": 유사도숫자,
  "레시피명2": 유사도숫자
}}"""

    try:
        print(f"[ai_service] 유사도 배치 시작: {len(recipe_names)}개 / 기준: {user_history}")
        data, provider = await llm_service.generate_json(
            prompt, temperature=0.1, max_tokens=1500, as_object=True
        )

        result = {}
        for name in recipe_names:
            sim = data.get(name, 0.0)
            result[name] = round(max(0.0, min(1.0, float(sim))), 4)

        print(f"[ai_service] 유사도 배치 완료({provider}): {result}")
        return result

    except Exception as e:
        print(f"[ai_service] 유사도 배치 오류 ({type(e).__name__}): {e}")
        return {name: 0.0 for name in recipe_names}