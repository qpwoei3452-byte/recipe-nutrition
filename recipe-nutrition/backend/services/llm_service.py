"""
llm_service.py

[역할]
ai_service.py / nutrition_service.py / cook_steps_service.py 세 곳에 각각
흩어져 있던 "Gemini 클라이언트 생성 → 호출 → JSON 파싱 → 에러 처리" 로직을
한 곳으로 모은 공용 레이어.

[동작 방식]
1. 항상 Gemini(gemini-2.5-flash-lite)로 먼저 시도한다.
2. 아래 경우에만 Groq로 자동 전환한다:
   - 429 (RESOURCE_EXHAUSTED, 무료 한도 초과)
   - 5xx (일시적 서버 오류)
   - 타임아웃
   - JSON 파싱 실패 (모델이 JSON이 아닌 텍스트를 반환한 경우)
3. 아래 경우는 Groq로 넘기지 않고 그대로 실패시킨다 (재시도해도 똑같이
   실패할 문제이므로 — 요청 형식/키/권한 문제):
   - 400 Bad Request
   - 401 Unauthorized
   - 403 Forbidden
4. Gemini도 Groq도 모두 실패하면 마지막 예외를 그대로 던진다.
   → 이 함수를 호출하는 각 서비스는 이미 자기만의 안전한 기본값
     (원본 텍스트 그대로 반환, 0으로 표시 등)을 갖고 있으므로, 여기서
     또 기본값을 만들지 않고 예외를 그대로 위로 올려서 기존 폴백이
     처리하게 한다 (중복 방지).

[Groq를 쓰려면]
.env 에 GROQ_API_KEY=... 를 추가하고, requirements.txt의 openai 패키지를
설치해야 한다. GROQ_API_KEY가 없으면 Groq 폴백 없이 Gemini만 사용하며,
Gemini가 실패하면 바로 예외가 올라간다 (기존과 동일한 동작).
"""

import asyncio
import json
from typing import Any, Tuple

from google import genai
from google.genai import types
from config import get_settings

_settings = get_settings()

# ── Gemini (1차) ─────────────────────────────────────────────
_gemini_client = genai.Client(api_key=_settings.gemini_api_key)
GEMINI_MODEL   = "gemini-2.5-flash-lite"

# ── Groq (폴백, 키가 있을 때만 활성화) ───────────────────────
_groq_client = None
GROQ_MODEL   = getattr(_settings, "groq_model", "") or "openai/gpt-oss-120b"

if getattr(_settings, "groq_api_key", ""):
    try:
        from openai import AsyncOpenAI
        _groq_client = AsyncOpenAI(
            api_key=_settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        print(f"[llm_service] Groq 폴백 활성화됨 (모델: {GROQ_MODEL})")
    except ImportError:
        print("[llm_service] 'openai' 패키지가 없어 Groq 폴백을 쓸 수 없습니다. "
              "pip install openai 로 설치하세요.")
else:
    print("[llm_service] GROQ_API_KEY가 없어 Groq 폴백이 비활성화되어 있습니다 "
          "(Gemini만 사용, 실패 시 바로 예외 발생).")

_TIMEOUT_SEC = 20

# [FIX] Gemini 한도가 다 차면 recommend() 한 번에 후보 레시피 수만큼(최대 50개)
# Groq 요청이 한꺼번에 몰려서 분당 토큰 한도(TPM)를 순식간에 넘겨버리는 문제가
# 있었음. 동시에 나갈 수 있는 Groq 요청 수를 제한해서 몰림을 완화.
_GROQ_CONCURRENCY = asyncio.Semaphore(3)


def _clean_json_text(text: str) -> str:
    return (text or "").strip().replace("```json", "").replace("```", "").strip()


async def _call_gemini(prompt: str, temperature: float, max_tokens: int) -> Any:
    response = await asyncio.wait_for(
        _gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            ),
        ),
        timeout=_TIMEOUT_SEC,
    )
    return json.loads(_clean_json_text(response.text))


async def _groq_request(prompt: str, temperature: float, max_tokens: int, use_json_object: bool) -> Any:
    kwargs = dict(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_completion_tokens=max_tokens,
        # [FIX] gpt-oss 계열은 기본적으로 답변 전에 "추론(reasoning)" 토큰을
        # 먼저 소모하는 모델이라, 토큰 예산이 빠듯하면 실제 답이 나오기도 전에
        # 잘려서 JSON이 깨지는 문제가 있었음(Unterminated string 에러).
        # reasoning_effort를 낮춰서 추론에 쓰는 토큰을 최소화.
        reasoning_effort="low",
    )
    if use_json_object:
        kwargs["response_format"] = {"type": "json_object"}

    response = await asyncio.wait_for(
        _groq_client.chat.completions.create(**kwargs),
        timeout=_TIMEOUT_SEC,
    )
    return json.loads(_clean_json_text(response.choices[0].message.content))


async def _call_groq(prompt: str, temperature: float, max_tokens: int, as_object: bool) -> Any:
    if _groq_client is None:
        raise RuntimeError("Groq 클라이언트가 초기화되지 않았습니다 (.env의 GROQ_API_KEY 확인)")

    # [FIX] reasoning_effort="low"로 낮춰도 추론에 어느 정도 토큰을 쓰기 때문에,
    # Gemini용으로 계산한 토큰 예산을 그대로 쓰면 부족해서 답이 잘림.
    # Groq 호출 시에는 예산을 2배로 넉넉하게 줌.
    groq_max_tokens = max_tokens * 2

    async with _GROQ_CONCURRENCY:
        try:
            return await _groq_request(prompt, temperature, groq_max_tokens, as_object)
        except Exception as e:
            # [FIX] response_format={"type":"json_object"} 강제 모드에서
            # 모델이 스키마를 못 맞추면 Groq가 400(json_validate_failed)으로
            # 거절하는 경우가 있었음. 강제 모드를 끄고 프롬프트 지시만으로
            # 한 번 더 시도 (프롬프트에 이미 "JSON만 반환" 지시가 있음).
            status_code = getattr(e, "status_code", None)
            if as_object and status_code == 400:
                print(f"[llm_service] Groq json_object 강제 모드 거부(400) — 강제 해제 후 재시도")
                return await _groq_request(prompt, temperature, groq_max_tokens, False)
            raise


def _is_fallback_worthy(e: Exception) -> bool:
    """이 예외를 Groq로 넘길 가치가 있는지 판단.
    429/5xx/타임아웃/JSON파싱실패 → 넘김. 400/401/403 → 넘기지 않음."""
    if isinstance(e, (asyncio.TimeoutError, json.JSONDecodeError)):
        return True
    code = getattr(e, "code", None)  # google.genai.errors.APIError.code
    if isinstance(code, int):
        return code == 429 or code >= 500
    return False


async def generate_json(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 1000,
    as_object: bool = True,
) -> Tuple[Any, str]:
    """
    Gemini로 먼저 시도하고, 429/타임아웃/5xx/JSON파싱실패 시에만 Groq로 전환한다.

    Returns:
        (파싱된 JSON, 실제로 응답한 provider — "gemini" 또는 "groq")

    Raises:
        원래 예외를 그대로 (Gemini가 400/401/403으로 실패했거나,
        Groq까지 실패한 경우) — 호출부의 기존 try/except가 처리함.
    """
    try:
        data = await _call_gemini(prompt, temperature, max_tokens)
        return data, "gemini"
    except Exception as e:
        if not _is_fallback_worthy(e):
            print(f"[llm_service] Gemini 오류({type(e).__name__}, 폴백 대상 아님): {e}")
            raise
        print(f"[llm_service] Gemini 실패({type(e).__name__}) → Groq로 전환 시도")

    data = await _call_groq(prompt, temperature, max_tokens, as_object)
    print("[llm_service] Groq 응답 성공")
    return data, "groq"