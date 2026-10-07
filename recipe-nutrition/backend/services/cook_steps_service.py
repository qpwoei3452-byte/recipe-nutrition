"""
cook_steps_service.py

[기능]
식약처 원본 조리 순서(축약된 전문가용 문장)를 초보자가 글만 읽고도
따라할 수 있도록 AI로 다시 풀어써주는 서비스 (Gemini 우선, 429/오류 시
llm_service가 Groq로 자동 전환).

[설계 원칙]
1. 원본은 절대 덮어쓰지 않음 — 항상 원본과 별도로 "해설본"을 만들어서
   프론트엔드에서 사용자가 원본/해설본을 토글로 전환해서 볼 수 있게 함.
2. 레시피 하나당 AI 호출은 최대 1회(전체 단계를 한 번에 배치 요청).
3. 한 번 만든 해설은 파일 캐시에 영구 저장 → 같은 레시피 재조회 시
   API 재호출 없이 즉시 응답.
4. AI 호출이 실패하거나 응답 형식이 이상해도 절대 화면이 깨지지 않도록,
   실패 시 "원본 문장을 그대로" 담은 안전한 폴백 결과를 반환한다.
   (오류 화면 대신 원본이라도 보여주는 것이 사용자 경험상 항상 낫다는 원칙)
"""

import json
import re
from pathlib import Path
from typing import Dict, List

from services import llm_service

_CACHE_DIR      = Path(__file__).parent / "cache"
_CACHE_FILE     = _CACHE_DIR / "cook_steps_ai_cache.json"
_CACHE_DIR.mkdir(exist_ok=True)


def _load_cache() -> Dict[str, List[Dict]]:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[cook_steps_service] 캐시 로드 실패: {e}")
    return {}


def _save_cache() -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(_CACHE, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[cook_steps_service] 캐시 저장 실패: {e}")


# [v2] 프롬프트가 바뀌었으므로 기존 캐시를 무효화합니다.
# Railway 재배포 후 캐시 파일이 없으면 자동으로 빈 딕셔너리로 시작합니다.
_CACHE_VERSION = "v2"
_raw_cache = _load_cache()
# 버전 키가 없는 구버전 캐시는 전부 버립니다
if _raw_cache.get("__version__") != _CACHE_VERSION:
    _CACHE: Dict[str, List[Dict]] = {"__version__": _CACHE_VERSION}
    _save_cache()
    print("[cook_steps_service] 프롬프트 버전 변경 — 구버전 캐시 초기화")
else:
    _CACHE = _raw_cache


def _fallback(original_steps: List[str]) -> List[Dict]:
    """AI를 쓸 수 없거나 실패했을 때: 원본 문장을 그대로 detail에 담아 반환.
    화면이 비거나 에러로 깨지는 일이 없도록 하는 안전판.

    [FIX] is_fallback 플래그를 추가했다. 이전에는 AI 해설과 원본 폴백이
    응답상 구분되지 않아, 사용자는 "쉽게 보기를 눌러도 원본과 똑같다"고
    느끼고 개발자는 기능 버그인지 AI 실패인지 알 수 없었다."""
    return [
        {
            "step":         i + 1,
            "original":     text,
            "detail":       text,
            "tip":          "",
            "duration_min": 0,
            "is_fallback":  True,
        }
        for i, text in enumerate(original_steps)
    ]


def _coerce_list(data):
    """[FIX] response_mime_type="application/json"만 주면 모델이 최상위를
    객체로 감싸 {"steps": [...]} 형태로 돌려주는 경우가 있다. 예전에는
    isinstance(data, list)가 False라는 이유로 통째로 버리고 원본 폴백을
    내보냈다. 객체로 와도 안에 든 배열을 꺼내 쓴다."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("steps", "result", "results", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        for v in data.values():
            if isinstance(v, list):
                return v
    return None


def _clean_step_text(text: str) -> str:
    # 조리 순서 원문 앞의 "1." 같은 번호 표기 제거 (프론트에서 이미 하던 처리와 동일)
    return re.sub(r"^\d+\.\s*", "", (text or "")).strip()


async def get_easy_steps(
    recipe_id: str,
    recipe_name: str,
    original_steps: List[str],
    ingredient_names: List[str],
) -> List[Dict]:
    """
    반환 형식 (원본 순서 그대로):
    [
      {
        "step": 1,
        "original": "원본 문장",
        "detail": "초보자용으로 풀어쓴 설명",
        "tip": "선택적 실전 팁 (없으면 빈 문자열)",
        "duration_min": 0 또는 대기/조리에 필요한 분 단위 정수
      },
      ...
    ]
    """
    cleaned = [_clean_step_text(s) for s in original_steps if _clean_step_text(s)]
    if not cleaned:
        return []

    if recipe_id and recipe_id in _CACHE:
        cached = _CACHE[recipe_id]
        if isinstance(cached, list) and len(cached) == len(cleaned):
            return cached
        # 캐시가 있지만 단계 수가 안 맞으면(레시피 데이터가 바뀐 경우) 새로 생성
        print(f"[cook_steps_service] 캐시 단계 수 불일치({recipe_id}) — 재생성")

    ing_line = ", ".join(ingredient_names[:20]) if ingredient_names else "정보 없음"
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(cleaned))

    prompt = f"""당신은 요리를 처음 해보는 왕초보를 가르치는 요리 선생님입니다.
아래 원본 조리 순서는 요리사 수준의 간결한 지시문이라 초보자는 따라하기 어렵습니다.
각 단계를 "처음 요리하는 사람이 실패 없이 그대로 따라할 수 있는" 수준으로 완전히 새로 풀어 쓰세요.

레시피: "{recipe_name}"
사용 재료: {ing_line}

【반드시 지켜야 할 규칙】
1. 원본의 짧은 지시를 최소 2~4문장으로 늘려 쓰세요. 원본 문장을 그대로 쓰면 안 됩니다.
2. 애매한 표현 금지 — 반드시 구체적인 기준으로 바꾸세요:
   - "적당히" → "중간 불(가스레인지 눈금 중간)에서"
   - "한소끔 끓인다" → "국물이 보글보글 기포가 생기며 끓어오를 때까지 약 2~3분"
   - "볶는다" → "중간 불에서 재료가 투명해질 때까지 약 3분간 계속 저어가며 볶으세요"
3. 초보자가 놓치기 쉬운 전처리/준비 동작을 적극 추가하세요.
   (예: "먼저 냄비 바닥이 완전히 달궈지도록 1분 예열하세요", "재료를 넣기 전 키친타월로 물기를 제거하세요")
4. 불 세기: 반드시 강불·중강불·중불·약불 중 하나로 명시하세요.
5. 시간: 대략적인 분 단위를 항상 제시하세요. ("약 5분", "3~5분")
6. 완성 확인 기준: 색깔·냄새·질감·소리 등 눈/코로 확인 가능한 신호를 쓰세요.
7. 존댓말(~하세요, ~주세요)로 작성하세요.
8. tip: 초보자가 실수하기 가장 쉬운 1가지만 적으세요. 없으면 빈 문자열.
9. duration_min: 끓이기/볶기/재우기 등 기다리는 시간이 있는 단계는 분 단위 정수. 썰기·씻기 등 즉시 행동은 0.

[원본 조리 순서]
{numbered}

반드시 아래 형식의 JSON 배열만 반환하세요 (마크다운·설명 없이):
[
  {{"detail": "초보자용 풀어쓴 설명 (2~4문장, 원본 문장 그대로 쓰면 안 됨)", "tip": "실수 방지 팁 또는 빈 문자열", "duration_min": 0}},
  ...
]"""

    try:
        print(f"[cook_steps_service] AI 조리순서 해설 생성 시작: '{recipe_name}' ({len(cleaned)}단계)")
        data, provider = await llm_service.generate_json(
            prompt,
            temperature=0.7,
            max_tokens=300 * len(cleaned) + 300,
            as_object=False,  # 최상위가 배열([...])이라 Groq의 json_object 강제는 끔
        )

        rows = _coerce_list(data)
        if rows is None:
            print(f"[cook_steps_service] AI 응답에서 배열을 찾지 못함({provider}) — 원본으로 폴백. 원본 응답: {str(data)[:300]}")
            return _fallback(cleaned)

        # [FIX] 개수가 안 맞는다고 전부 버리지 않는다. AI가 단계를 합치거나
        # 쪼개면 흔히 어긋나는데, 예전에는 그때마다 통째로 원본 폴백이 나가서
        # "쉽게 보기가 원본과 똑같다"의 원인 중 하나였다.
        # 받은 만큼만 쓰고 모자란 단계만 원본으로 채운다.
        if len(rows) != len(cleaned):
            print(f"[cook_steps_service] AI 응답 개수 불일치({provider}): "
                  f"요청 {len(cleaned)} / 응답 {len(rows)} — 받은 만큼만 사용")

        result = []
        for i, orig in enumerate(cleaned):
            row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else None
            if row is None:
                result.append({
                    "step": i + 1, "original": orig, "detail": orig,
                    "tip": "", "duration_min": 0, "is_fallback": True,
                })
                continue
            detail_text = str(row.get("detail") or "").strip() or orig
            tip_text    = str(row.get("tip") or "").strip()
            try:
                duration = int(row.get("duration_min") or 0)
            except (TypeError, ValueError):
                duration = 0
            duration = max(0, min(duration, 240))  # 4시간 이상은 비현실적 → 상한선

            result.append({
                "step":         i + 1,
                "original":     orig,
                "detail":       detail_text,
                "tip":          tip_text,
                "duration_min": duration,
                # 해설이 원본과 사실상 같으면 폴백으로 표시
                "is_fallback":  detail_text.strip() == orig.strip(),
            })

        # [FIX] 전부 원본 폴백인 결과를 캐시에 저장하면, 할당량이 회복된 뒤에도
        # 영원히 원본만 보이게 된다. 하나라도 AI 해설이 있을 때만 저장한다.
        if recipe_id and not all(r.get("is_fallback") for r in result):
            _CACHE[recipe_id] = result
            _save_cache()

        print(f"[cook_steps_service] AI 조리순서 해설 완료({provider}): '{recipe_name}' {len(result)}단계")
        return result

    except Exception as e:
        print(f"[cook_steps_service] AI 조리순서 해설 오류 ({type(e).__name__}): "
              f"{str(e)[:200]} — 원본으로 폴백")
        return _fallback(cleaned)