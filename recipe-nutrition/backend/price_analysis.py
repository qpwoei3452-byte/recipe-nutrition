"""
price_analysis.py
==================
전체 레시피 재료비 분포 분석 스크립트

실행 방법:
  1. 이 파일을 backend/ 폴더 안에 저장
  2. 터미널에서:
     cd recipe-nutrition/recipe-nutrition/backend
     python price_analysis.py

결과:
  - 총 레시피 수 / 최솟값·중앙값·최댓값·평균
  - 구간별 가격 분포 (개수 + %)
  - 레시피별 상세 가격 목록 (price_result.csv 저장)
"""

import asyncio
import csv
import re
import sys
from pathlib import Path
from statistics import mean, median, stdev

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from services import price_service
from services.recipe_service import _load_env_file, _format, _safe_json

# ── 설정 ────────────────────────────────────────────────────────
ENV      = _load_env_file()
API_KEY  = (ENV.get("MFDS_API_KEY") or "").strip()
BASE_URL = "http://openapi.foodsafetykorea.go.kr/api"
PAGE_SZ  = 100   # 한 번에 가져올 레시피 수


# ── 전체 레시피 가져오기 (페이지네이션) ─────────────────────────
async def fetch_all_recipes() -> list:
    """식약처 API를 페이지 단위로 반복 호출해 전체 레시피를 가져옴"""
    all_rows = []
    start = 1

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # 1) 총 개수 먼저 확인
        url  = f"{BASE_URL}/{API_KEY}/COOKRCP01/json/1/1"
        resp = await client.get(url)
        data = _safe_json(resp, "total_check")
        total = int(data.get("COOKRCP01", {}).get("total_count", 0))
        if total == 0:
            print("  레시피를 가져오지 못했습니다. .env의 MFDS_API_KEY를 확인해주세요.")
            return []

        print(f"  → 전체 레시피 수: {total}개, {PAGE_SZ}개씩 {-(-total//PAGE_SZ)}번 요청")

        # 2) 페이지 단위로 전체 수집
        page = 1
        while start <= total:
            end  = min(start + PAGE_SZ - 1, total)
            url  = f"{BASE_URL}/{API_KEY}/COOKRCP01/json/{start}/{end}"
            resp = await client.get(url)
            rows = _safe_json(resp, f"page{page}").get("COOKRCP01", {}).get("row", [])
            all_rows.extend(rows)
            print(f"  → 페이지 {page}: {start}~{end}번 ({len(rows)}개) 수신 (누계 {len(all_rows)}개)")
            start += PAGE_SZ
            page  += 1

    return all_rows


# ── 가격 계산 ───────────────────────────────────────────────────
async def calc_price(row: dict) -> float:
    """단일 레시피 행의 재료비 합산"""
    formatted = await _format(row)
    return float(formatted.get("price_total_krw", 0) or 0)


# ── 메인 ───────────────────────────────────────────────────────
async def main():
    print("=" * 55)
    print("  전체 레시피 재료비 분포 분석")
    print("=" * 55)

    # 1) 전체 레시피 수집
    print("\n[1/3] 식약처 전체 레시피 수신 중...")
    rows = await fetch_all_recipes()
    if not rows:
        return
    print(f"  완료: 총 {len(rows)}개")

    # 2) 가격 계산 (병렬)
    print(f"\n[2/3] 재료비 계산 중 (처음 실행 시 시간이 걸립니다)...")
    tasks  = [calc_price(row) for row in rows]
    prices_raw = await asyncio.gather(*tasks)

    results = []
    for row, price in zip(rows, prices_raw):
        results.append({"name": row.get("RCP_NM", ""), "price": price})

    results.sort(key=lambda x: x["price"])

    # 3) 통계 계산
    print(f"\n[3/3] 통계 계산 중...")

    valid   = [r for r in results if r["price"] > 0]
    prices  = [r["price"] for r in valid]
    all_cnt = len(results)
    val_cnt = len(valid)

    print("\n" + "=" * 55)
    print("  분석 결과")
    print("=" * 55)
    print(f"\n  총 레시피               : {all_cnt}개")
    print(f"  재료비 > 0 (계산 성공)  : {val_cnt}개")
    print(f"  재료비 = 0 (계산 실패)  : {all_cnt - val_cnt}개")

    if prices:
        min_r = valid[0]
        max_r = valid[-1]
        print(f"\n  최솟값   : {min(prices):>10,.0f}원  ({min_r['name']})")
        print(f"  중앙값   : {median(prices):>10,.0f}원")
        print(f"  평균값   : {mean(prices):>10,.0f}원")
        print(f"  최댓값   : {max(prices):>10,.0f}원  ({max_r['name']})")
        if len(prices) > 1:
            print(f"  표준편차 : {stdev(prices):>10,.0f}원")

    brackets = [
        ("~1,000원",       0,      1000),
        ("1,000~2,000원",  1000,   2000),
        ("2,000~3,000원",  2000,   3000),
        ("3,000~4,000원",  3000,   4000),
        ("4,000~5,000원",  4000,   5000),
        ("5,000~7,000원",  5000,   7000),
        ("7,000~10,000원", 7000,  10000),
        ("10,000원 이상",  10000, 999999),
    ]

    print(f"\n  {'구간':<17}  {'개수':>5}  {'비율':>6}  막대")
    print(f"  {'-'*52}")
    for label, lo, hi in brackets:
        cnt = sum(1 for p in prices if lo < p <= hi)
        pct = cnt / val_cnt * 100 if val_cnt else 0
        bar = "█" * int(pct / 2.5)
        print(f"  {label:<17}  {cnt:>4}개  {pct:>5.1f}%  {bar}")

    # CSV 저장
    csv_path = Path(__file__).parent / "price_result.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["순위", "레시피명", "재료비(원)"])
        writer.writeheader()
        for i, r in enumerate(valid, 1):
            writer.writerow({"순위": i, "레시피명": r["name"], "재료비(원)": int(r["price"])})

    print(f"\n  상세 결과 저장: {csv_path}")
    print("\n" + "=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
