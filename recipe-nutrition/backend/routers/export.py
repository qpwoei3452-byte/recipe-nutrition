"""
routers/export.py
분석 결과를 CSV 또는 엑셀(.xlsx)로 내보내기.

POST /api/export/csv    → CSV 파일 다운로드
POST /api/export/excel  → Excel 파일 다운로드
"""

import io
import csv
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import pandas as pd

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportRequest(BaseModel):
    recipe_name: str
    ingredients: list[dict]
    nutrition_total: dict
    price_total_krw: float
    errors: list[str]


@router.post("/csv")
async def export_csv(req: ExportRequest):
    """레시피 분석 결과를 CSV로 내보냅니다."""
    output = io.StringIO()
    writer = csv.writer(output)

    # 헤더
    writer.writerow([
        "재료명(원본)", "표준명", "양(원본)", "단위", "환산량(g)",
        "열량(kcal)", "단백질(g)", "지방(g)", "탄수화물(g)", "나트륨(mg)",
        "가격(원)", "오류여부", "오류내용"
    ])

    # 재료별 행
    for ing in req.ingredients:
        writer.writerow([
            ing.get("raw_name", ""),
            ing.get("standard_nm", ""),
            ing.get("amount_raw", ""),
            ing.get("unit_raw", ""),
            ing.get("amount_g", ""),
            ing.get("energy_kcal", ""),
            ing.get("protein_g", ""),
            ing.get("fat_g", ""),
            ing.get("carb_g", ""),
            ing.get("sodium_mg", ""),
            ing.get("price_krw", ""),
            "Y" if ing.get("has_error") else "N",
            ing.get("error_msg", ""),
        ])

    # 합계 행
    writer.writerow([])
    nt = req.nutrition_total
    writer.writerow([
        "【합계】", "", "", "", nt.get("total_g", ""),
        nt.get("energy_kcal", ""), nt.get("protein_g", ""),
        nt.get("fat_g", ""), nt.get("carb_g", ""), nt.get("sodium_mg", ""),
        req.price_total_krw, "", ""
    ])

    # 오류 목록
    if req.errors:
        writer.writerow([])
        writer.writerow(["【누락/불일치 오류】"])
        for err in req.errors:
            writer.writerow([err])

    output.seek(0)
    filename = f"{req.recipe_name}_분석결과.csv"

    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),  # BOM 포함 (Excel 한글 깨짐 방지)
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    )


@router.post("/excel")
async def export_excel(req: ExportRequest):
    """레시피 분석 결과를 Excel(.xlsx)로 내보냅니다."""
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        # ── Sheet 1: 재료별 분석 ──────────────────────────────
        rows = []
        for ing in req.ingredients:
            rows.append({
                "재료명(원본)":   ing.get("raw_name", ""),
                "표준명":         ing.get("standard_nm", ""),
                "사용량(g)":      ing.get("amount_g", ""),
                "단위환산메모":   ing.get("unit_note", ""),
                "열량(kcal)":     ing.get("energy_kcal", ""),
                "단백질(g)":      ing.get("protein_g", ""),
                "지방(g)":        ing.get("fat_g", ""),
                "탄수화물(g)":    ing.get("carb_g", ""),
                "나트륨(mg)":     ing.get("sodium_mg", ""),
                "가격(원)":       ing.get("price_krw", ""),
                "오류":           ing.get("error_msg", "") if ing.get("has_error") else "",
            })

        df_ing = pd.DataFrame(rows)
        df_ing.to_excel(writer, sheet_name="재료별분석", index=False)

        # ── Sheet 2: 영양 합계 ───────────────────────────────
        nt = req.nutrition_total
        df_total = pd.DataFrame([{
            "레시피":      req.recipe_name,
            "총중량(g)":   nt.get("total_g", 0),
            "열량(kcal)":  nt.get("energy_kcal", 0),
            "단백질(g)":   nt.get("protein_g", 0),
            "지방(g)":     nt.get("fat_g", 0),
            "탄수화물(g)": nt.get("carb_g", 0),
            "당류(g)":     nt.get("sugar_g", 0),
            "식이섬유(g)": nt.get("fiber_g", 0),
            "나트륨(mg)":  nt.get("sodium_mg", 0),
            "칼슘(mg)":    nt.get("calcium_mg", 0),
            "총재료비(원)": req.price_total_krw,
        }])
        df_total.to_excel(writer, sheet_name="영양합계", index=False)

        # ── Sheet 3: 오류 목록 ───────────────────────────────
        if req.errors:
            df_errors = pd.DataFrame({"오류내용": req.errors})
            df_errors.to_excel(writer, sheet_name="누락오류목록", index=False)

    output.seek(0)
    filename = f"{req.recipe_name}_분석결과.xlsx"

    return StreamingResponse(
        iter([output.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    )
