import asyncio
import httpx
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from services import nutrition_service, price_service


def _load_env_file() -> dict:
    env = {}
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        print(f"[recipe_service] .env 파일을 찾지 못함: {env_path}")
        return env
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    except Exception as e:
        print(f"[recipe_service] .env 읽기 실패: {e}")
    return env


_ENV    = _load_env_file()
MY_API_KEY = (os.getenv("MFDS_API_KEY") or _ENV.get("MFDS_API_KEY", "")).strip()
BASE_URL   = "http://openapi.foodsafetykorea.go.kr/api"

RECIPE_CACHE: Dict[str, Dict] = {}

# ─────────────────────────────────────────────────────────────
# 개 단위 → g 환산 (확장)
# ─────────────────────────────────────────────────────────────
PIECE_GRAMS = {
    "오렌지": 200.0,    "당근": 200.0,      "양파": 180.0,      "감자": 180.0,
    "사과": 250.0,      "토마토": 150.0,    "방울토마토": 12.0,
    "달걀": 50.0,       "계란": 50.0,       "마늘": 5.0,        "대파": 100.0,
    "두부": 300.0,      "순두부": 350.0,    "청양고추": 10.0,   "고추": 10.0,
    "양배추": 900.0,    "애호박": 250.0,    "오이": 200.0,      "무": 1000.0,
    "배추": 2000.0,     "감자": 180.0,      "고구마": 200.0,    "가지": 200.0,
    "파프리카": 180.0,  "피망": 150.0,      "홍피망": 150.0,    "청피망": 150.0,
    "양배추잎": 50.0,   "배춧잎": 50.0,     "상추잎": 5.0,      "깻잎": 2.0,
    "버섯": 50.0,       "표고버섯": 30.0,   "팽이버섯": 150.0,  "새송이버섯": 100.0,
    "느타리버섯": 100.0, "양송이버섯": 20.0,
    "사과": 250.0,      "배": 500.0,        "딸기": 15.0,       "귤": 100.0,
    "레몬": 100.0,      "자두": 60.0,       "복숭아": 200.0,
    "메추리알": 10.0,   "새우": 15.0,       "바지락": 10.0,     "꼬막": 15.0,
    "생강": 10.0,       "감": 200.0,        "바나나": 120.0,
}

# ─────────────────────────────────────────────────────────────
# 한국 단위 → g 환산
# ─────────────────────────────────────────────────────────────
KOREAN_UNIT_GRAMS = {
    "모":   {"두부": 300.0,  "순두부": 350.0, "default": 300.0},
    "토막": {"고등어": 150.0,"갈치": 150.0,   "default": 100.0},
    "마리": {"꽁치": 150.0,  "멸치": 3.0,     "새우": 15.0, "default": 150.0},
    "뿌리": {"대파": 100.0,  "파": 100.0,     "default": 100.0},
    "포기": {"배추": 2000.0, "양배추": 900.0, "default": 500.0},
    "줄기": {"미나리": 5.0,  "셀러리": 50.0,  "default": 20.0},
    "단":   {"시금치": 200.0,"부추": 150.0,   "default": 150.0},
    "쪽":   {"마늘": 5.0,    "생강": 10.0,    "default": 10.0},
    "장":   {"김": 2.0,      "default": 10.0},
    "알":   {"달걀": 50.0,   "계란": 50.0,    "메추리알": 10.0, "default": 50.0},
    "근":   {"default": 600.0},
    "송이": {"버섯": 30.0,   "표고버섯": 30.0,"default": 30.0},
    "봉지": {"순두부": 350.0,"두부": 300.0,   "default": 200.0},
}

# ─────────────────────────────────────────────────────────────
# 복합 재료명 → 핵심 재료명 매핑 (최우선 적용)
# 짧은 단어가 긴 단어 안에서 잘못 매칭되는 문제 방지
# ─────────────────────────────────────────────────────────────
COMPOUND_MAP = {
    # 버터류
    "무염버터": "버터",     "가염버터": "버터",     "발효버터": "버터",
    # 간장류
    "저염간장": "간장",     "국간장": "간장",        "양조간장": "간장",
    "진간장": "간장",       "왜간장": "간장",
    # 소금류
    "저염소금": "소금",     "저나트륨소금": "소금",  "천일염": "소금",
    "구운소금": "소금",     "죽염": "소금",
    # 고추류 (고추냉이·고추기름은 고추와 다름)
    "고추냉이": "고추냉이", "고추기름": "고추기름",  "고춧가루": "고춧가루",
    "청양고추": "청양고추", "홍고추": "고추",         "풋고추": "고추",
    # 토마토류
    "방울토마토": "방울토마토", "토마토케첩": "케첩", "토마토소스": "토마토소스",
    # 파류
    "대파": "대파",         "쪽파": "쪽파",          "파채": "대파",
    "실파": "쪽파",         "움파": "대파",
    # 두부류
    "순두부": "순두부",     "연두부": "두부",         "부침두부": "두부",
    "찌개두부": "두부",
    # 깨류
    "통깨": "참깨",         "볶은통깨": "참깨",       "볶은 통깨": "참깨",
    "검은깨": "검은깨",     "흑임자": "검은깨",       "볶은 흑임자": "검은깨",
    # 기름류
    "올리브유": "올리브유", "올리브오일": "올리브유",
    "참기름": "참기름",     "들기름": "들기름",       "식용유": "식용유",
    "포도씨유": "식용유",   "카놀라유": "식용유",     "현미유": "식용유",
    # 식초류
    "발사믹식초": "발사믹식초", "사과식초": "식초",   "현미식초": "식초",
    "양조식초": "식초",     "포도식초": "식초",
    # 술류
    "청주": "청주",         "미림": "맛술",           "맛술": "맛술",
    "요리술": "맛술",       "화이트와인": "화이트와인",
    # 육류
    "닭가슴살": "닭가슴살", "닭다리살": "닭고기",     "닭안심": "닭고기",
    "돼지목살": "돼지고기", "돼지삼겹살": "삼겹살",   "소고기": "소고기",
    "쇠고기": "소고기",     "우육": "소고기",         "돈육": "돼지고기",
    "돼지등심": "돼지고기", "돼지앞다리살": "돼지고기",
    # 채소류 복합명
    "무청": "무청",         "무우": "무",             "왜무": "무",
    "쑥갓": "쑥갓",         "미나리": "미나리",
    # 가공식품
    "통조림 햄": "햄",      "스팸": "햄",             "맛살": "맛살",
    "어묵": "어묵",         "찰어묵": "어묵",
    # 조미료
    "마요네즈": "마요네즈", "머스터드": "머스터드",   "케첩": "케첩",
    "굴소스": "굴소스",     "굴 소스": "굴소스",
    # 견과·씨앗
    "땅콩버터": "땅콩버터", "피넛버터": "땅콩버터",
    "해바라기씨": "해바라기씨", "호박씨": "호박씨",
    # 유제품
    "버터": "버터",         "생크림": "생크림",       "플레인요거트": "플레인요거트",
    "그릭요거트": "플레인요거트", "슬라이스치즈": "치즈",
    # 해산물
    "칵테일새우": "새우",   "대하": "새우",           "흰새우": "새우",
    "바지락": "바지락",     "모시조개": "바지락",
    # 면·곡류
    "당면": "당면",         "불린 당면": "당면",       "소면": "소면",
    "칼국수면": "소면",     "쌀국수": "쌀국수",
    # 매실
    "매실액": "매실액",     "매실청": "매실액",        "매실진액": "매실액",
    # 기름류
    "튀김기름": "식용유",   "포도씨유": "식용유",      "카놀라유": "식용유",
    "현미유": "식용유",     "해바라기유": "식용유",
    # 채소 복합명 (수식어 제거)
    "가정 간편식 재료 배추": "배추", "간편식 재료 배추": "배추",
    "어린잎채소": "어린잎채소", "베이비채소": "어린잎채소",
    # 소스류
    "소스 칠리소스": "칠리소스",   "칠리소스": "칠리소스",
    "소스 크림소스": "생크림",     "크림소스": "생크림",
    "소스 토마토소스": "토마토소스", "토마토소스": "토마토소스",
    "소스 데리야키소스": "간장",   "데리야키소스": "간장",
    # 떡류
    "증편": "증편",         "가래떡": "떡",            "절편": "떡",
    "인절미": "떡",         "송편": "떡",
    # 밀가루 종류
    "박력분": "밀가루",     "강력분": "밀가루",         "중력분": "밀가루",
    "통밀가루": "밀가루",   "쌀가루": "쌀가루",
    # 청 종류
    "레몬청": "유자청",     "자몽청": "유자청",         "유자청": "유자청",
    # 치즈 종류
    "리코타 치즈": "치즈",  "리코타치즈": "치즈",       "크림치즈": "치즈",
    "파마산치즈": "치즈",   "체다치즈": "치즈",
    # 기타
    "족발": "족발",         "보쌈": "보쌈",             "수육": "수육",
    "바나나": "바나나",
    # 김치류
    "묵은지": "김치",       "묵은 김치": "김치",         "열무김치": "김치",
    "깍두기": "김치",       "총각김치": "김치",           "백김치": "김치",
    # 미역류
    "미역 줄기": "미역줄기", "미역줄기": "미역줄기",
    "건미역": "미역",        "생미역": "미역",
    # 발효원종
    "블루베리 발효원종": "발효원종", "천연발효원종": "발효원종",
    "사워도우": "발효원종",
    # 통삼겹
    "통삼겹": "삼겹살",     "통삼겹살": "삼겹살",
    # 복합 재료명 (요리명+재료명 패턴)
    "청국장리조뜨 밥": "즉석밥", "리조또 밥": "즉석밥", "볶음밥 밥": "즉석밥",
    "밥": "즉석밥",
    "가정 간편식 재료 배추": "배추", "간편식 재료 배추": "배추",
    "가정간편식재료배추": "배추",
    # 해조류면
    "해조국수": "해조국수",  "곤약면": "곤약",
    # 올리브류
    "블랙올리브": "블랙올리브", "그린올리브": "블랙올리브",
}

# ─────────────────────────────────────────────────────────────
# 일반 재료 aliases (길이 내림차순 — 긴 단어 먼저 매칭)
# ─────────────────────────────────────────────────────────────
_ALIASES = sorted([
    "방울토마토", "토마토", "오렌지즙", "오렌지", "양배추", "당근", "양파", "감자",
    "사과", "두부", "순두부", "계란", "달걀", "대파", "마늘", "청양고추", "고추",
    "돼지고기", "소고기", "닭고기", "닭가슴살", "삼겹살",
    "부침가루", "식용유", "참기름", "간장", "된장", "고추장", "쌈장",
    "김치", "애호박", "오이", "무", "버섯", "표고버섯", "팽이버섯",
    "새송이버섯", "느타리버섯", "파프리카", "피망", "생강", "쪽파",
    "브로콜리", "시금치", "부추", "미나리", "깻잎", "상추", "쑥갓",
    "고춧가루", "설탕", "물엿", "참깨", "깨", "검은깨",
    "두유", "우유", "생크림", "버터", "달걀", "계란",
    "새우", "오징어", "멸치", "황태", "황태채", "북어채",
    "쌀", "밀가루", "소면", "당면",
    "된장", "고추장", "간장", "식초", "참기름",
    "올리브유", "마요네즈", "케첩", "머스터드",
    "감자", "고구마", "연근", "도라지",
    "김치", "두부", "어묵", "맛살",
    "잣", "호두", "아몬드", "땅콩",
], key=len, reverse=True)  # 길이 내림차순


def _n(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except Exception:
        return 0.0


def _save_to_cache(row: Dict):
    recipe_id = str(row.get("RCP_SEQ") or "")
    if recipe_id:
        RECIPE_CACHE[recipe_id] = row


def _normalize_ingredient_name(name: str) -> str:
    """
    재료명에서 핵심 재료명 추출.

    순서:
    1) COMPOUND_MAP 딕셔너리 우선 체크 (복합명 정확 매핑)
    2) 일반 정규화 (괄호·단위 제거)
    3) _ALIASES 리스트 (길이 내림차순으로 긴 단어 먼저 매칭)
    """
    s = (name or "").strip()

    # 1) 복합명 딕셔너리 우선 체크
    # 정확히 일치하거나, 재료명이 COMPOUND_MAP 키를 포함하는지 확인
    for compound, mapped in COMPOUND_MAP.items():
        if compound == s or s.startswith(compound) or s.endswith(compound):
            return mapped
        # 공백 포함 패턴 (예: "무염 버터")
        normalized_key = compound.replace(" ", "")
        normalized_s   = s.replace(" ", "")
        if normalized_key in normalized_s and len(compound) >= 3:
            return mapped

    # 2) 일반 정규화
    s = re.sub(r"^[●•·]\s*", "", s)
    s = re.sub(r"^(주재료|부재료|소스|양념|재료)\s*[:：]?\s*", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\d+(?:\.\d+)?\s*(kg|g|mg|ml|l|개|큰술|작은술|컵|모|뿌리|토막|마리|장|쪽|포기|단|줄기|알|송이|봉지)", " ", s, flags=re.I)
    s = re.sub(r"\d+\s*/\s*\d+\s*개", " ", s)
    s = re.sub(r"(적당량|약간|조금|소량)", "", s)
    s = re.sub(r"[^\w가-힣]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # 3) aliases 매칭 (길이 내림차순 — 긴 단어 먼저)
    for a in _ALIASES:
        if a in s:
            return a

    return s


def _extract_amount_g(text: str, ingredient_name: str) -> float:
    s = text or ""

    # 1) kg
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", s, re.I)
    if m:
        return float(m.group(1)) * 1000

    # 2) g (최우선)
    m = re.search(r"(\d+(?:\.\d+)?)\s*g(?!\w)", s, re.I)
    if m:
        return float(m.group(1))

    # 3) mg
    m = re.search(r"(\d+(?:\.\d+)?)\s*mg", s, re.I)
    if m:
        return float(m.group(1)) / 1000

    # 4) ml / L
    m = re.search(r"(\d+(?:\.\d+)?)\s*ml", s, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*[lL](?!\w)", s)
    if m:
        return float(m.group(1)) * 1000

    # 5) 큰술·스푼 (15ml)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:큰술|스푼|tbsp)", s, re.I)
    if m:
        return float(m.group(1)) * 15.0

    # 6) 작은술·티스푼 (5ml)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:작은술|티스푼|tsp)", s, re.I)
    if m:
        return float(m.group(1)) * 5.0

    # 7) 컵 (200ml)
    m = re.search(r"(\d+(?:\.\d+)?)\s*컵", s)
    if m:
        return float(m.group(1)) * 200.0

    # 8) 한국 전통 단위
    for unit, unit_map in KOREAN_UNIT_GRAMS.items():
        # 분수: "1/5모"
        m = re.search(rf"(\d+)\s*/\s*(\d+)\s*{unit}", s)
        if m:
            num, den = float(m.group(1)), float(m.group(2))
            if den > 0:
                gram = unit_map.get(ingredient_name) or unit_map.get("default", 100.0)
                return (num / den) * gram
        # 일반: "2모"
        m = re.search(rf"(\d+(?:\.\d+)?)\s*{unit}", s)
        if m:
            count = float(m.group(1))
            gram  = unit_map.get(ingredient_name) or unit_map.get("default", 100.0)
            return count * gram

    # 9) 분수 개: "1/4개"
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*개", s)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if den > 0:
            return (num / den) * PIECE_GRAMS.get(ingredient_name, 0.0)

    # 10) 개수
    m = re.search(r"(\d+(?:\.\d+)?)\s*개", s)
    if m:
        return float(m.group(1)) * PIECE_GRAMS.get(ingredient_name, 0.0)

    # 11) 단위 없는 숫자 → g으로 간주
    # 예) "풋마늘 20", "건오징어 5", "밀가루 1.25"
    m = re.search(r"(\d+(?:\.\d+)?)\s*$", s.strip())
    if m:
        return float(m.group(1))

    return 0.0


def _split_chunks(line: str) -> List[str]:
    chunks = [c.strip() for c in re.split(r",|·|•", line) if c.strip()]
    return chunks if chunks else [line.strip()]


# [FIX] "굴", "무", "파", "배"처럼 실제로 존재하는 한 글자짜리 한국어
# 재료명이 있음. 기존에는 len(standard_nm) < 2 조건으로 이런 재료들까지
# 전부 걸러내서, 조리 순서에는 "굴을 씻어서..."라고 나오는데 재료 목록에는
# 굴이 아예 안 뜨는 문제(메뉴-레시피 불일치)가 있었음.
# 흔히 쓰이는 한 글자 재료를 화이트리스트로 두고 이 재료들은 필터를 통과시킴.
_SINGLE_CHAR_INGREDIENTS = {
    # 채소/해산물 (기존)
    "굴", "무", "파", "배", "콩", "김", "잣", "깨", "엿", "술", "쑥", "게",
    # 곡물/전분 (신규)
    "쌀", "밥", "떡", "팥", "밤",
    # 기타 (신규)
    "꿀", "마", "감", "차",
}


def _is_valid_ingredient_name(standard_nm: str) -> bool:
    if not standard_nm:
        return False
    if len(standard_nm) >= 2:
        return True
    return standard_nm in _SINGLE_CHAR_INGREDIENTS


def _parse_ingredients(parts_text: str) -> List[Dict]:
    if not parts_text:
        return []

    # <br> 태그 줄바꿈 처리 후 파싱
    text = parts_text.replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    ingredients = []

    for line in lines:
        # 불릿 제거 + 대괄호 섹션명 전체 제거 (줄 어디서든)
        line    = re.sub(r"^[●•·]\s*", "", line).strip()
        cleaned = re.sub(r"\[.*?\]\s*", "", line).strip()

        for chunk in _split_chunks(cleaned):
            chunk = chunk.strip()
            if not chunk:
                continue

            standard_nm = _normalize_ingredient_name(chunk)
            if not _is_valid_ingredient_name(standard_nm):
                continue

            # 숫자 없는 재료 ("약간", "적당량") → 소량 기본값 2g 적용
            has_number = bool(re.search(r"\d", chunk))
            if has_number:
                amount_g = _extract_amount_g(chunk, standard_nm)
            else:
                # "약간", "적당량" 표기 → 2g 기본값
                if re.search(r"(약간|적당량|조금|소량)", chunk):
                    amount_g = 2.0
                else:
                    continue  # 숫자도 없고 약간도 없으면 제외

            ingredients.append({
                "raw_name":               chunk,
                "standard_nm":            standard_nm,
                "amount_g":               round(amount_g, 1),
                "protein_g":              0.0,
                "fat_g":                  0.0,
                "carb_g":                 0.0,
                "sugar_g":                0.0,
                "fiber_g":                0.0,
                "sodium_mg":              0.0,
                "calcium_mg":             0.0,
                "price_krw":              0.0,
                "price_unit":             "",
                "price_matched_name":     "",
                "nutrition_matched_name": "",
            })

    return ingredients


async def _enrich_ingredient(ing: Dict) -> Dict:
    try:
        nutrition_info, price_info = await asyncio.gather(
            nutrition_service.get_nutrition_for_ingredient(
                ing.get("standard_nm", ""),
                float(ing.get("amount_g", 0.0) or 0.0),
            ),
            price_service.get_price_for_ingredient(
                ing.get("standard_nm", ""),
                float(ing.get("amount_g", 0.0) or 0.0),
            )
        )
        ing["protein_g"]              = float(nutrition_info.get("protein_g", 0.0) or 0.0)
        ing["fat_g"]                  = float(nutrition_info.get("fat_g",      0.0) or 0.0)
        ing["carb_g"]                 = float(nutrition_info.get("carb_g",     0.0) or 0.0)
        ing["sugar_g"]                = float(nutrition_info.get("sugar_g",    0.0) or 0.0)
        ing["fiber_g"]                = float(nutrition_info.get("fiber_g",    0.0) or 0.0)
        ing["sodium_mg"]              = float(nutrition_info.get("sodium_mg",  0.0) or 0.0)
        ing["calcium_mg"]             = float(nutrition_info.get("calcium_mg", 0.0) or 0.0)
        ing["nutrition_matched_name"] = nutrition_info.get("matched_name", "")
        ing["price_krw"]              = float(price_info.get("price_krw", 0.0) or 0.0)
        ing["price_unit"]             = price_info.get("unit", "")
        ing["price_matched_name"]     = price_info.get("matched_name", "")
    except Exception as e:
        print(f"[recipe_service] enrich 실패: {ing.get('standard_nm')} / {e}")
    return ing


async def _enrich_ingredients(ingredients: List[Dict]) -> List[Dict]:
    if not ingredients:
        return []

    # [FIX] 재료마다 각각 Gemini를 부르면 레시피 하나에 재료 개수만큼(N번)
    # API 호출이 발생함. 로컬/캐시에 없는 재료명을 먼저 모아서 딱 한 번의
    # 배치 요청으로 채워놓은 뒤, 개별 enrich는 캐시에서 즉시 읽어가게 함.
    missing = [
        ing.get("standard_nm", "")
        for ing in ingredients
        if ing.get("standard_nm") and not nutrition_service.has_local_or_cached(ing["standard_nm"])
    ]
    if missing:
        await nutrition_service.estimate_nutrition_batch(missing)

    tasks = [_enrich_ingredient(dict(ing)) for ing in ingredients]
    return await asyncio.gather(*tasks)


def _safe_json(resp: httpx.Response, label: str) -> Dict:
    try:
        return resp.json()
    except Exception as e:
        print(f"[{label}] JSON 파싱 실패: {e}, status={resp.status_code}")
        return {}


async def _format(row: Dict) -> Dict:
    steps = []
    for i in range(1, 21):
        key  = f"MANUAL{i:02d}"
        desc = (row.get(key) or "").replace("\\n", "\n").strip()
        if desc:
            steps.append({"step": i, "desc": desc})

    ingredients = _parse_ingredients(row.get("RCP_PARTS_DTLS", ""))
    ingredients = await _enrich_ingredients(ingredients)

    # [FIX] sugar_g/fiber_g/calcium_mg는 식약처 레시피 API가 애초에 제공하지 않는
    # 필드라 항상 0으로 고정되어 있었음 → 재료별 폴백 영양DB(nutrition_service)
    # 값을 합산해서 채워줌. energy_kcal/protein_g/fat_g/carb_g/sodium_mg는
    # 식약처가 레시피 단위로 직접 제공하는 공식 값이라 그대로 사용.
    sugar_sum    = round(sum(float(ing.get("sugar_g",    0.0) or 0.0) for ing in ingredients), 2)
    fiber_sum    = round(sum(float(ing.get("fiber_g",    0.0) or 0.0) for ing in ingredients), 2)
    calcium_sum  = round(sum(float(ing.get("calcium_mg", 0.0) or 0.0) for ing in ingredients), 2)

    return {
        "id":        str(row.get("RCP_SEQ") or ""),
        "name":      str(row.get("RCP_NM") or ""),
        "category":  row.get("RCP_PAT2") or "",
        "method":    row.get("RCP_WAY2") or "",
        "image_url": row.get("ATT_FILE_NO_MAIN") or "",
        "steps":     steps,
        "source":    "식약처",
        "ingredients": ingredients,
        "nutrition_total": {
            "energy_kcal": _n(row.get("INFO_ENG")),
            "protein_g":   _n(row.get("INFO_PRO")),
            "fat_g":       _n(row.get("INFO_FAT")),
            "carb_g":      _n(row.get("INFO_CAR")),
            "sugar_g":     sugar_sum,
            "fiber_g":     fiber_sum,
            "sodium_mg":   _n(row.get("INFO_NA")),
            "calcium_mg":  calcium_sum,
            "total_g":     _n(row.get("INFO_WGT")),
        },
        "price_total_krw": round(
            sum(float(ing.get("price_krw", 0.0) or 0.0) for ing in ingredients), 1
        ),
        "errors": []
    }


async def search_recipes(query: str) -> List[Dict]:
    print(f"[search_recipes] MFDS_API_KEY length={len(MY_API_KEY)}")
    if not MY_API_KEY:
        return []

    url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/50"
    if query:
        url += f"/RCP_NM={quote(query)}"
    print(f"[search_recipes] URL={url}")

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url)
            data = _safe_json(resp, "search_recipes")
            rows = data.get("COOKRCP01", {}).get("row", [])
            result = []
            for r in rows:
                _save_to_cache(r)
                result.append({
                    "id":        str(r.get("RCP_SEQ") or ""),
                    "name":      str(r.get("RCP_NM") or ""),
                    "category":  r.get("RCP_PAT2") or "기타",
                    "method":    r.get("RCP_WAY2") or "기타",
                    "calories":  _n(r.get("INFO_ENG")),
                    "image_url": r.get("ATT_FILE_NO_MAIN") or "",
                    "tags":      []
                })
            print(f"[recipe_service] search 결과 {len(result)}건, 캐시 {len(RECIPE_CACHE)}건")
            return result
        except Exception as e:
            print(f"[search_recipes 오류] {e}")
            return []


async def get_recipe_detail(recipe_id: str, name: str = None) -> Optional[Dict]:
    recipe_id = str(recipe_id)
    cached = RECIPE_CACHE.get(recipe_id)
    if cached:
        print(f"[recipe_service] 캐시 적중: {recipe_id}")
        return await _format(cached)

    if not MY_API_KEY:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            if name and name.strip():
                u_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/50/RCP_NM={quote(name.strip())}"
                res   = await client.get(u_url)
                data  = _safe_json(res, "detail_by_name")
                rows  = data.get("COOKRCP01", {}).get("row", [])
                for r in rows:
                    _save_to_cache(r)
                    if str(r.get("RCP_SEQ") or "") == recipe_id:
                        return await _format(r)
                for r in rows:
                    if (r.get("RCP_NM") or "").strip() == name.strip():
                        return await _format(r)

            id_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/1/RCP_SEQ={recipe_id}"
            res    = await client.get(id_url)
            data   = _safe_json(res, "detail_by_id")
            rows   = data.get("COOKRCP01", {}).get("row", [])
            if rows:
                r = rows[0]
                _save_to_cache(r)
                if str(r.get("RCP_SEQ") or "") == recipe_id:
                    return await _format(r)

            return {"id": recipe_id, "name": name or "", "category": "", "method": "",
                    "image_url": "", "steps": [], "source": "식약처", "ingredients": [],
                    "nutrition_total": {"energy_kcal":0.0,"protein_g":0.0,"fat_g":0.0,
                    "carb_g":0.0,"sugar_g":0.0,"fiber_g":0.0,"sodium_mg":0.0,
                    "calcium_mg":0.0,"total_g":0.0},
                    "price_total_krw": 0.0, "errors": ["식약처 상세 조회 실패"]}

        except Exception as e:
            print(f"[get_recipe_detail 오류] {e}")
            return {"id": recipe_id, "name": name or "", "category": "", "method": "",
                    "image_url": "", "steps": [], "source": "식약처", "ingredients": [],
                    "nutrition_total": {"energy_kcal":0.0,"protein_g":0.0,"fat_g":0.0,
                    "carb_g":0.0,"sugar_g":0.0,"fiber_g":0.0,"sodium_mg":0.0,
                    "calcium_mg":0.0,"total_g":0.0},
                    "price_total_krw": 0.0, "errors": [f"예외: {str(e)}"]}
