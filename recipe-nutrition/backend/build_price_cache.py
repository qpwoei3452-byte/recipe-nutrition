"""
build_price_cache.py — 전체 레시피 사전 처리 배치 스크립트

식약처 API 페이지네이션으로 전체 레시피를 가져와서
재료별 가격을 계산하고 recipe_price_snapshot.json에 저장.

실행:
  cd backend
  python build_price_cache.py          (전체)
  python build_price_cache.py --limit 50  (테스트)
  python build_price_cache.py --reset  (캐시 초기화 후 재계산)
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from services.price_service import get_price_for_ingredient


# ─────────────────────────────────────────────────────────────
# 환경변수
# ─────────────────────────────────────────────────────────────
def _load_env():
    env = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).resolve().parent / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        print(f"[build] .env 읽기 실패: {e}")
    return env


_ENV       = _load_env()
_API_KEY   = (_ENV.get("MFDS_API_KEY") or "").strip()
_BASE_URL  = "http://openapi.foodsafetykorea.go.kr/api"
_PAGE_SIZE = 100   # 한 번에 가져올 레시피 수

# 출력 경로
_CACHE_DIR     = Path(__file__).parent / "services" / "cache"
_SNAPSHOT_FILE = _CACHE_DIR / "recipe_price_snapshot.json"
_CACHE_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────
# 식약처 API — 페이지네이션으로 전체 레시피 수집
# ─────────────────────────────────────────────────────────────
async def _fetch_all_recipes(limit: int = 0):
    """식약처 API를 페이지 단위로 반복 호출해 전체 레시피 수신"""
    if not _API_KEY:
        print("[build] MFDS_API_KEY 없음")
        return []

    all_rows = []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # 총 레시피 수 먼저 확인
        res   = await client.get(f"{_BASE_URL}/{_API_KEY}/COOKRCP01/json/1/1")
        total = int(res.json().get("COOKRCP01", {}).get("total_count", 0))

        if total == 0:
            print("[build] 레시피를 가져오지 못했습니다.")
            return []

        if limit > 0:
            total = min(total, limit)

        print(f"  → 전체 레시피: {total}개, {_PAGE_SIZE}개씩 {-(-total//_PAGE_SIZE)}번 요청")

        start = 1
        page  = 1
        while start <= total:
            end  = min(start + _PAGE_SIZE - 1, total)
            url  = f"{_BASE_URL}/{_API_KEY}/COOKRCP01/json/{start}/{end}"
            res  = await client.get(url)
            rows = res.json().get("COOKRCP01", {}).get("row", [])
            all_rows.extend(rows)
            print(f"  → 페이지 {page}: {start}~{end}번 ({len(rows)}개) 누계 {len(all_rows)}개")
            start += _PAGE_SIZE
            page  += 1

    return all_rows


# ─────────────────────────────────────────────────────────────
# 재료 파싱 (recipe_service와 동일한 로직)
# ─────────────────────────────────────────────────────────────
import re
# recipe_service의 _parse_ingredients 직접 사용 (br 처리·대괄호 제거 포함)
from services.recipe_service import _parse_ingredients as _rs_parse

def _parse_ingredients(parts_text: str):
    """recipe_service의 파싱 로직을 그대로 사용 (수정사항 자동 반영)"""
    ings = _rs_parse(parts_text)
    return [{"standard_nm": i["standard_nm"], "amount_g": i["amount_g"]} for i in ings]


# ─────────────────────────────────────────────────────────────
# 메인 배치
# ─────────────────────────────────────────────────────────────
async def build_cache(limit: int = 0, reset: bool = False):
    print("=" * 55)
    print("  사전 처리 배치 시작")
    print("=" * 55)

    # 기존 스냅샷 로드
    snapshot: dict = {}
    if not reset and _SNAPSHOT_FILE.exists():
        try:
            snapshot = json.loads(_SNAPSHOT_FILE.read_text(encoding="utf-8"))
            print(f"  기존 스냅샷 로드: {len(snapshot)}개 (이미 계산된 항목 스킵)")
        except Exception:
            pass

    # 전체 레시피 수신 (페이지네이션)
    print("\n[1/2] 식약처 전체 레시피 수신 중...")
    rows = await _fetch_all_recipes(limit=limit)
    if not rows:
        return
    print(f"  완료: {len(rows)}개")

    # 가격 계산 (순차 처리)
    print(f"\n[2/2] 가격 계산 중...")
    total   = len(rows)
    done    = 0
    skipped = 0
    errors  = 0

    for row in rows:
        recipe_id = str(row.get("RCP_SEQ") or "")
        name      = str(row.get("RCP_NM") or "")

        # 이미 계산된 항목 스킵
        if recipe_id in snapshot and not reset:
            skipped += 1
            done    += 1
            if done % 50 == 0 or done == total:
                print(f"  진행: {done}/{total} ({done/total*100:.0f}%) | 스킵: {skipped} | 오류: {errors}")
            continue

        # 재료 파싱
        ingredients = _parse_ingredients(row.get("RCP_PARTS_DTLS", ""))
        price_total = 0.0
        ing_prices  = []

        for ing in ingredients:
            raw_nm   = ing["standard_nm"]
            amount_g = ing["amount_g"]
            if not raw_nm or amount_g <= 0:
                continue
            try:
                result = await get_price_for_ingredient(raw_nm, amount_g)
                ing_prices.append({
                    "name":     raw_nm,
                    "amount_g": amount_g,
                    "price":    result["price_krw"],
                    "source":   result["source"],
                })
                price_total += result["price_krw"]
            except Exception as e:
                errors += 1

        snapshot[recipe_id] = {
            "name":        name,
            "price_total": round(price_total, 1),
            "ingredients": ing_prices,
            "updated_at":  time.time(),
        }

        # 10개마다 저장 (중간에 끊겨도 보존)
        done += 1
        if done % 10 == 0 or done == total:
            _SNAPSHOT_FILE.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            pct = done / total * 100
            print(f"  진행: {done}/{total} ({pct:.0f}%) | 스킵: {skipped} | 오류: {errors}")

    # 최종 저장
    _SNAPSHOT_FILE.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 통계
    prices = sorted(v["price_total"] for v in snapshot.values() if v["price_total"] > 0)

    print("\n" + "=" * 55)
    print("  배치 완료")
    print("=" * 55)
    print(f"  처리 레시피: {len(snapshot)}개")
    if prices:
        import statistics
        print(f"  최솟값: {min(prices):>10,.0f}원")
        print(f"  중앙값: {statistics.median(prices):>10,.0f}원")
        print(f"  평균값: {statistics.mean(prices):>10,.0f}원")
        print(f"  최댓값: {max(prices):>10,.0f}원")

        brackets = [
            ("~1,000원",      0,     1000),
            ("1,000~3,000원", 1000,  3000),
            ("3,000~5,000원", 3000,  5000),
            ("5,000~10,000원",5000,  10000),
            ("10,000원 이상", 10000, 999999),
        ]
        print(f"\n  구간별 분포:")
        for label, lo, hi in brackets:
            cnt = sum(1 for p in prices if lo < p <= hi)
            pct = cnt / len(prices) * 100
            print(f"    {label:<17}: {cnt:4}개 ({pct:5.1f}%)")

    print(f"\n  저장 위치: {_SNAPSHOT_FILE}")
    print("=" * 55)


def get_price_from_snapshot(recipe_id: str) -> dict:
    if not _SNAPSHOT_FILE.exists():
        return {}
    try:
        snapshot = json.loads(_SNAPSHOT_FILE.read_text(encoding="utf-8"))
        return snapshot.get(str(recipe_id), {})
    except Exception:
        return {}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="처리할 레시피 수 (0=전체)")
    parser.add_argument("--reset", action="store_true",  help="캐시 초기화 후 전체 재계산")
    args = parser.parse_args()
    asyncio.run(build_cache(limit=args.limit, reset=args.reset))
