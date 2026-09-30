# ================================================================
# test_integration.py
# 파이프라인 전체 통합 테스트
# 식약처 API → 농진청/nutrition_service → KAMIS/price_service → 추천
#
# 실행: cd backend && python test_integration.py
# 전제: .env 파일에 MFDS_API_KEY 가 있어야 함
#       KAMIS 키가 없으면 fallback 가격으로 동작 (정상)
# ================================================================

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from services import recipe_service, recommend_service


# ── 검색할 키워드 목록 ──────────────────────────────────────────
# 식약처 DB에 있는 실제 레시피를 키워드로 검색함
# 키워드를 바꾸면 다른 레시피를 테스트할 수 있음
SEARCH_QUERIES = [
    "",        # 빈 문자열 = 전체 레시피 (최대 50개)
    "닭",      # 닭고기 계열 레시피
    "두부",    # 두부 계열 레시피
    "계란",    # 계란 계열 레시피
]

# ── 테스트할 추천 모드 ──────────────────────────────────────────
MODES = ["가성비", "고단백", "저칼로리", "기본"]


async def test_pipeline(query: str, mode: str, top_n: int = 3):
    """
    단일 파이프라인 테스트:
    1. 식약처 API로 레시피 검색
    2. 각 레시피 상세 조회 (nutrition_service + price_service 호출됨)
    3. 추천 알고리즘 적용
    4. 결과 출력
    """
    label = f'"{query}"' if query else "전체"
    print(f"\n{'━'*55}")
    print(f"  검색: {label}  |  모드: {mode}")
    print(f"{'━'*55}")

    # ── Step 1: 식약처 API 레시피 검색 ──────────────────────────
    print("  [1/3] 식약처 API 레시피 검색 중...")
    summaries = await recipe_service.search_recipes(query)

    if not summaries:
        print("  ❌ 레시피를 찾지 못했습니다.")
        print("     → .env 파일의 MFDS_API_KEY 를 확인하세요.")
        return

    print(f"  ✓ {len(summaries)}개 레시피 검색됨: {[r['name'] for r in summaries[:5]]}{'...' if len(summaries)>5 else ''}")

    # ── Step 2: 상세 조회 (영양 + 가격 API 호출됨) ──────────────
    print(f"  [2/3] 영양성분·가격 데이터 조회 중 ({len(summaries)}개)...")
    tasks   = [recipe_service.get_recipe_detail(r["id"], r["name"]) for r in summaries]
    details = await asyncio.gather(*tasks)
    details = [d for d in details if d]

    # 데이터 품질 점검
    no_nutrition = [d["name"] for d in details if d.get("nutrition_total", {}).get("energy_kcal", 0) == 0]
    no_price     = [d["name"] for d in details if d.get("price_total_krw", 0) == 0]

    print(f"  ✓ 상세 조회 완료: {len(details)}개")

    if no_nutrition:
        print(f"  ⚠ 영양정보 없음 ({len(no_nutrition)}개): {no_nutrition[:3]}{'...' if len(no_nutrition)>3 else ''}")
        print("     → nutrition_service 에 재료명 매핑 추가 필요")

    if no_price:
        print(f"  ⚠ 가격정보 없음 ({len(no_price)}개): {no_price[:3]}{'...' if len(no_price)>3 else ''}")
        print("     → KAMIS 키 미설정이거나 price_service fallback 미등록 재료")

    # ── Step 3: 추천 알고리즘 적용 ──────────────────────────────
    print(f"  [3/3] [{mode}] 모드로 추천 점수 계산 중...")
    result = recommend_service.recommend(details, mode=mode, top_n=top_n)

    if not result:
        print("  ❌ 추천 결과 없음")
        return

    print(f"\n  ── 추천 결과 (상위 {top_n}개) ──")
    for i, r in enumerate(result, 1):
        nt   = r.get("nutrition_total", {})
        s    = r.get("_scores", {})
        ings = r.get("ingredients", [])
        print(f"""
  {i}위  {r['name']}  (최종점수: {r['score']:.4f})
       칼로리   : {nt.get('energy_kcal', 0):.0f} kcal  (정규화: {s.get('calorie', 0):.3f})
       단백질   : {nt.get('protein_g', 0):.1f} g      (정규화: {s.get('protein', 0):.3f})
       탄수화물 : {nt.get('carb_g', 0):.1f} g
       지방     : {nt.get('fat_g', 0):.1f} g
       재료비   : {int(r.get('price_total_krw', 0)):,} 원  (정규화: {s.get('price', 0):.3f})
       조리시간 : {r.get('cook_time_min', 0)} 분    (정규화: {s.get('time', 0):.3f})
       재료수   : {len(ings)} 개
       추천이유 : {r['reason']}""")


async def run_all():
    print("\n" + "="*55)
    print("  통합 테스트 시작")
    print("  식약처 API → 영양/가격 조회 → 추천 알고리즘")
    print("="*55)

    failed = 0

    for query in SEARCH_QUERIES:
        for mode in MODES:
            try:
                await test_pipeline(query, mode, top_n=3)
            except Exception as e:
                print(f"  ❌ 오류 발생 (query={query}, mode={mode}): {e}")
                failed += 1

    print(f"\n{'='*55}")
    if failed == 0:
        print("  ✅ 모든 테스트 통과!")
    else:
        print(f"  ⚠ {failed}개 테스트 실패. 위 로그를 확인하세요.")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(run_all())