"""
build_allergy_cache.py — 알레르기 분류 배치 스크립트

전체 레시피 재료명을 Gemini로 식약처 22종 알레르기 분류
→ services/cache/allergy_map.json 저장

실행:
  cd backend
  python build_allergy_cache.py
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

# ─────────────────────────────────────────────────────────────
# 환경변수
# ─────────────────────────────────────────────────────────────
def _load_env():
    env = {}
    for path in [Path(__file__).parent.parent / ".env",
                 Path(__file__).parent / ".env"]:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
            break
    return env

_ENV        = _load_env()
GEMINI_KEY  = (os.getenv("GEMINI_API_KEY") or _ENV.get("GEMINI_API_KEY", "")).strip()
GEMINI_URL  = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}"

_CACHE_DIR    = Path(__file__).parent / "services" / "cache"
_ALLERGY_FILE = _CACHE_DIR / "allergy_map.json"
_CACHE_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 식약처 22종 알레르기 공식 분류
# ─────────────────────────────────────────────────────────────
ALLERGY_22 = [
    "알류", "우유", "메밀", "땅콩", "대두", "밀",
    "고등어", "게", "새우", "돼지고기", "복숭아", "토마토",
    "아황산류", "호두", "닭고기", "쇠고기", "오징어", "조개류",
    "잣", "아몬드", "캐슈넛", "피스타치오"
]

# ─────────────────────────────────────────────────────────────
# 규칙 기반 사전 (Gemini 호출 전 1차 처리)
# 정확도 보장을 위해 명확한 재료는 직접 지정
# ─────────────────────────────────────────────────────────────
RULE_MAP = {
    # 알류
    "달걀": ["알류"], "계란": ["알류"], "메추리알": ["알류"],
    "달걀흰자": ["알류"], "달걀노른자": ["알류"],
    # 우유
    "우유": ["우유"], "버터": ["우유"], "치즈": ["우유"],
    "생크림": ["우유"], "요거트": ["우유"], "플레인요거트": ["우유"],
    "슬라이스치즈": ["우유"], "모차렐라치즈": ["우유"],
    "리코타치즈": ["우유"], "크림치즈": ["우유"],
    # 메밀
    "메밀": ["메밀"], "메밀면": ["메밀"], "냉면": ["메밀"],
    # 땅콩
    "땅콩": ["땅콩"], "땅콩버터": ["땅콩"],
    # 대두
    "두부": ["대두"], "된장": ["대두"], "간장": ["대두"],
    "두유": ["대두"], "청국장": ["대두"], "콩나물": ["대두"],
    "순두부": ["대두"], "콩": ["대두"], "대두": ["대두"],
    "쌈장": ["대두"], "고추장": ["대두"],
    # 밀
    "밀가루": ["밀"], "소면": ["밀"], "박력분": ["밀"],
    "강력분": ["밀"], "중력분": ["밀"], "빵가루": ["밀"],
    "당면": ["밀"], "라면": ["밀"], "우동": ["밀"],
    # 고등어
    "고등어": ["고등어"],
    # 게
    "게": ["게"], "꽃게": ["게"], "대게": ["게"],
    "킹크랩": ["게"], "왕게": ["게"], "털게": ["게"],
    "게살": ["게"], "게맛살": ["게"],
    # 새우
    "새우": ["새우"], "대하": ["새우"], "칵테일새우": ["새우"],
    "흰다리새우": ["새우"], "왕새우": ["새우"], "새우살": ["새우"],
    # 돼지고기
    "돼지고기": ["돼지고기"], "삼겹살": ["돼지고기"],
    "목살": ["돼지고기"], "족발": ["돼지고기"],
    "햄": ["돼지고기"], "베이컨": ["돼지고기"],
    "소시지": ["돼지고기"], "스팸": ["돼지고기"],
    # 복숭아
    "복숭아": ["복숭아"], "천도복숭아": ["복숭아"],
    # 토마토
    "토마토": ["토마토"], "방울토마토": ["토마토"],
    "토마토소스": ["토마토"], "케첩": ["토마토"],
    # 아황산류
    "와인": ["아황산류"], "화이트와인": ["아황산류"],
    "레드와인": ["아황산류"],
    # 호두
    "호두": ["호두"],
    # 닭고기
    "닭고기": ["닭고기"], "닭가슴살": ["닭고기"],
    "닭다리": ["닭고기"], "닭안심": ["닭고기"],
    # 쇠고기
    "소고기": ["쇠고기"], "쇠고기": ["쇠고기"],
    "안심": ["쇠고기"], "등심": ["쇠고기"],
    "갈비": ["쇠고기"], "불고기": ["쇠고기"],
    # 오징어
    "오징어": ["오징어"], "건오징어": ["오징어"],
    "오징어채": ["오징어"], "낙지": ["오징어"],
    "주꾸미": ["오징어"], "문어": ["오징어"],
    # 조개류
    "굴": ["조개류"], "전복": ["조개류"], "홍합": ["조개류"],
    "바지락": ["조개류"], "꼬막": ["조개류"], "백합": ["조개류"],
    "모시조개": ["조개류"], "재첩": ["조개류"],
    # 잣
    "잣": ["잣"],
    # 아몬드
    "아몬드": ["아몬드"],
    # 캐슈넛
    "캐슈넛": ["캐슈넛"],
    # 피스타치오
    "피스타치오": ["피스타치오"],
    # 무관 재료 (알레르기 없음)
    "물": [], "소금": [], "설탕": [], "후추": [], "참기름": [],
    "식용유": [], "올리브유": [], "참깨": [], "깨": [],
    "마늘": [], "생강": [], "대파": [], "양파": [], "당근": [],
    "배추": [], "무": [], "감자": [], "고구마": [], "쌀": [],
    "고춧가루": [], "식초": [], "물엿": [], "올리고당": [],
}


# ─────────────────────────────────────────────────────────────
# 재료명 수집
# ─────────────────────────────────────────────────────────────
def collect_ingredients() -> set:
    snapshot_file = _CACHE_DIR / "recipe_price_snapshot.json"
    if not snapshot_file.exists():
        print("[build_allergy] recipe_price_snapshot.json 없음")
        return set()

    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    names = set()
    for v in snapshot.values():
        for ing in v.get("ingredients", []):
            name = ing.get("name", "").strip()
            if name and len(name) >= 2:
                names.add(name)
    print(f"[build_allergy] 전체 재료명: {len(names)}개")
    return names


# ─────────────────────────────────────────────────────────────
# Gemini로 알레르기 분류
# ─────────────────────────────────────────────────────────────
async def gemini_classify(names: list) -> dict:
    if not GEMINI_KEY:
        print("[build_allergy] GEMINI_API_KEY 없음")
        return {}

    prompt = f"""다음 식재료 목록에서 각 재료가 식약처 지정 알레르기 유발 식품 22종 중 어디에 해당하는지 분류해주세요.

식약처 22종: {', '.join(ALLERGY_22)}

재료 목록:
{chr(10).join(f'- {n}' for n in names)}

규칙:
1. 해당하는 알레르기만 배열로 반환 (없으면 빈 배열 [])
2. 반드시 JSON만 반환 (설명 없이)
3. 형식: {{"재료명": ["알레르기1", "알레르기2"], ...}}

예시:
{{"꽃게": ["게"], "달걀노른자": ["알류"], "쌀": []}}"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(GEMINI_URL, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0}
            })
            if res.status_code != 200:
                print(f"[build_allergy] Gemini 오류: {res.status_code}")
                return {}

            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            # JSON 추출
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                return {}
            return json.loads(m.group(0))
    except Exception as e:
        print(f"[build_allergy] Gemini 예외: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# 메인 배치
# ─────────────────────────────────────────────────────────────
async def build_allergy_cache():
    print("=" * 55)
    print("  알레르기 분류 배치 시작")
    print("=" * 55)

    # 기존 파일 로드
    allergy_map = {}
    if _ALLERGY_FILE.exists():
        try:
            allergy_map = json.loads(_ALLERGY_FILE.read_text(encoding="utf-8"))
            print(f"  기존 분류 로드: {len(allergy_map)}개")
        except Exception:
            pass

    # 재료명 수집
    all_names = collect_ingredients()
    if not all_names:
        print("재료명 없음 - recipe_price_snapshot.json 먼저 생성해주세요")
        return

    # 규칙 기반 먼저 처리
    rule_count = 0
    for name in all_names:
        if name not in allergy_map and name in RULE_MAP:
            allergy_map[name] = RULE_MAP[name]
            rule_count += 1
    print(f"  규칙 기반 처리: {rule_count}개")

    # Gemini로 처리할 재료 (아직 분류 안 된 것)
    remaining = [n for n in all_names if n not in allergy_map or allergy_map[n] == []]
    print(f"  Gemini 처리 필요: {len(remaining)}개")

    if not remaining:
        print("  모든 재료 분류 완료 (Gemini 불필요)")
    else:
        # 50개씩 배치
        BATCH = 50
        batches = [remaining[i:i+BATCH] for i in range(0, len(remaining), BATCH)]
        print(f"  배치 수: {len(batches)}개")

        for i, batch in enumerate(batches):
            print(f"  배치 {i+1}/{len(batches)}: {len(batch)}개 처리 중...")
            result = await gemini_classify(batch)

            # 결과 병합
            for name in batch:
                allergy_map[name] = result.get(name, [])

            # 중간 저장
            _ALLERGY_FILE.write_text(
                json.dumps(allergy_map, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            await asyncio.sleep(2)  # Rate limit 방지

    # 최종 저장
    _ALLERGY_FILE.write_text(
        json.dumps(allergy_map, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 통계
    has_allergy = {k: v for k, v in allergy_map.items() if v}
    print("\n" + "=" * 55)
    print("  배치 완료")
    print("=" * 55)
    print(f"  전체 재료: {len(allergy_map)}개")
    print(f"  알레르기 있는 재료: {len(has_allergy)}개")
    print(f"  저장 위치: {_ALLERGY_FILE}")

    # 알레르기 분포
    from collections import Counter
    cnt = Counter()
    for v in allergy_map.values():
        for a in v:
            cnt[a] += 1
    print("\n  알레르기 분포:")
    for allergy, count in cnt.most_common():
        print(f"    {allergy}: {count}개 재료")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(build_allergy_cache())
