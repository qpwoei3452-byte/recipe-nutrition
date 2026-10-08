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
    "오렌지": 200.0,    "당근": 200.0,      "양파": 180.0,
    "달걀": 50.0,       "계란": 50.0,       "마늘": 5.0,        "대파": 100.0,
    "두부": 300.0,      "순두부": 350.0,    "청양고추": 10.0,   "고추": 10.0,
    "양배추": 900.0,    "애호박": 250.0,    "오이": 200.0,      "무": 1000.0,
    "배추": 2000.0,     "감자": 180.0,      "고구마": 200.0,    "가지": 200.0,
    "파프리카": 180.0,  "피망": 150.0,      "홍피망": 150.0,    "청피망": 150.0,
    "양배추잎": 50.0,   "배춧잎": 50.0,     "상추잎": 5.0,      "깻잎": 2.0,
    "버섯": 50.0,       "표고버섯": 30.0,   "팽이버섯": 150.0,  "새송이버섯": 100.0,
    "느타리버섯": 100.0, "양송이버섯": 20.0,
    "토마토": 150.0,    "방울토마토": 12.0,
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
    "방울토마토": "방울토마토", "토마토케첩": "케첩", # 파류
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
# [FIX] COMPOUND_MAP을 길이 내림차순으로 정렬해 둔다.
# dict 삽입 순서대로 매칭하면 짧은 키가 먼저 걸려 오매핑이 생긴다.
_COMPOUND_SORTED = sorted(COMPOUND_MAP.items(), key=lambda kv: -len(kv[0]))

_ALIASES = sorted([
    "방울토마토", "토마토", "오렌지즙", "오렌지", "양배추", "당근", "양파", "감자",
    "사과", "두부", "순두부", "계란", "달걀", "대파", "마늘", "청양고추",
    "고추", "돼지고기", "소고기", "닭고기", "닭가슴살", "삼겹살", "부침가루", "식용유",
    "참기름", "간장", "된장", "고추장", "쌈장", "김치", "애호박", "오이",
    "무", "버섯", "표고버섯", "팽이버섯", "새송이버섯", "느타리버섯", "파프리카", "피망",
    "생강", "쪽파", "브로콜리", "시금치", "부추", "미나리", "깻잎", "상추",
    "쑥갓", "고춧가루", "설탕", "물엿", "참깨", "깨", "검은깨", "두유",
    "우유", "생크림", "버터", "새우", "오징어", "멸치", "황태", "황태채",
    "북어채", "쌀", "밀가루", "소면", "당면", "식초", "올리브유", "마요네즈",
    "케첩", "머스터드", "고구마", "연근", "도라지", "어묵", "맛살", "잣",
    "호두", "아몬드", "땅콩",
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
    # [FIX] 예전에는 dict 삽입 순서대로 돌아서, 짧은 키가 긴 키보다 먼저
    # 걸리면 엉뚱한 재료로 매핑됐다. 긴 키부터 검사한다(_ALIASES와 동일 방식).
    for compound, mapped in _COMPOUND_SORTED:
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
    # [FIX] COMPOUND_MAP이 "스팸"·"통조림 햄"을 "햄"으로 정규화하는데,
    # "햄"이 이 목록에 없어 _is_valid_ingredient_name()에서 걸러져
    # 재료 자체가 통째로 사라지고 있었다. 부대찌개 계열 레시피에서
    # 햄이 영양·가격 계산에 전혀 반영되지 않던 원인.
    "햄",
    # 기타 (신규)
    "꿀", "마", "감", "차",
    # [FIX] '물'이 1글자라 재료 목록에서 통째로 빠지고 있었다.
    # 국물요리는 물이 300~500ml를 차지하는데도 재료합에 안 잡혀
    # 인분 수 역산이 크게 어긋났다(표고버섯 청경채국 재료합 72g ← 실제 372g).
    # 타 레시피 사이트도 '물 1L'를 재료로 표시한다.
    # 가격은 FREE_INGREDIENTS로 0원, 영양도 0이므로 계산에는 영향이 없다.
    "물",
}


# [FIX] 식약처 재료 문자열에는 실제 재료가 아닌 안내 문구가 섞여 있다.
# 예) "2인분 기준", "재료", "소스", "육수 재료 물".
# 이것들이 재료로 잡히면 (1) 화면에 이상한 재료명이 뜨고
# (2) 영양·가격 조회 API를 쓸데없이 호출해 할당량을 태운다.
_NON_INGREDIENT_EXACT = {
    "기준", "재료", "주재료", "부재료", "소스", "양념", "고명",
    "장식", "준비", "필수", "선택", "곁들임", "토핑",
}


# ─────────────────────────────────────────────────────────────
# 사용량을 '조리 단위'로 되돌리기
#
# 식약처는 재료를 g으로만 적는 레시피가 많은데(주꾸미 40g, 마늘 3g),
# 가정에서 요리할 때는 저울보다 '1마리', '2/3쪽'이 쓰기 쉽다.
# 타 레시피 서비스도 조리 단위를 쓴다.
#   우리의식탁 '두부 1모'  새미네부엌 '대파 1/5대'  이밥차 '마늘 3쪽'
#
# 다만 식약처는 1인분 표준 분량이라 양이 매우 작아(주꾸미김치찌개 총 137g)
# 전부 환산하면 '김치 0.02포기', '두부 0.03모'처럼 쓸모없는 값이 된다.
# 그래서 **분모 4 이하의 깔끔한 분수로 떨어질 때만** 조리 단위로 바꾸고,
# 그렇지 않으면 g을 그대로 둔다.
#
# 환산 기준은 이미 쓰고 있는 PIECE_GRAMS / KOREAN_UNIT_GRAMS 그대로다.
# (영양·가격 계산에 쓰는 값과 같아야 화면과 계산이 어긋나지 않는다)
# ─────────────────────────────────────────────────────────────
from fractions import Fraction

# 재료 → (조리 단위, 1단위당 g). KOREAN_UNIT_GRAMS를 뒤집어 만든다.
# [FIX] 만개의레시피 「계량법 안내」의 공개 눈대중표로 보정.
# 우리 값이 실제 식재료 크기와 달랐던 것들이다.
#   당근 200g → 150g,  대파 100g → 140g,  돼지고기 200g → 100g
_EYE_MEASURE = {
    "양파": 170.0, "당근": 150.0, "대파": 140.0, "마늘": 5.0, "생강": 5.0,
}
PIECE_GRAMS.update(_EYE_MEASURE)
# 대파는 '뿌리'보다 '대'가 통용된다 (만개의레시피: 대파 1/2대 = 70g)
KOREAN_UNIT_GRAMS.setdefault("대", {})["대파"] = 140.0
KOREAN_UNIT_GRAMS["대"].setdefault("default", 140.0)
KOREAN_UNIT_GRAMS.setdefault("톨", {})["마늘"] = 5.0
KOREAN_UNIT_GRAMS["톨"]["생강"] = 5.0
KOREAN_UNIT_GRAMS["톨"].setdefault("default", 5.0)
KOREAN_UNIT_GRAMS["토막"]["돼지고기"] = 100.0
KOREAN_UNIT_GRAMS["토막"]["소고기"] = 100.0
KOREAN_UNIT_GRAMS["토막"].setdefault("생선", 85.0)
KOREAN_UNIT_GRAMS["토막"]["무"] = 150.0

_DISPLAY_UNIT: Dict[str, tuple] = {}
for _unit, _table in KOREAN_UNIT_GRAMS.items():
    for _nm, _g in _table.items():
        if _nm != "default" and _nm not in _DISPLAY_UNIT:
            _DISPLAY_UNIT[_nm] = (_unit, _g)
# 개수로 세는 재료는 '개'
for _nm, _g in PIECE_GRAMS.items():
    _DISPLAY_UNIT.setdefault(_nm, ("개", _g))
# 통용되는 단위로 덮어쓰기 (KOREAN_UNIT_GRAMS 순회 순서에 좌우되지 않도록)
_DISPLAY_UNIT["대파"] = ("대", 140.0)
_DISPLAY_UNIT["마늘"] = ("쪽", 5.0)
_DISPLAY_UNIT["생강"] = ("톨", 5.0)
_DISPLAY_UNIT["무"]   = ("토막", 150.0)
# 가루·액체·양념류는 숟가락이 자연스럽다 (1작은술 = 5g, 1큰술 = 15g)
# 캐시 1,146개 레시피에서 'g으로만 표시되던 재료'를 빈도순으로 뽑아 채웠다.
for _nm in (
    # 장·소스·액체
    "간장", "국간장", "진간장", "저염간장", "참기름", "들기름", "식용유", "올리브유",
    "포도씨유", "식초", "맛술", "청주", "된장", "고추장", "쌈장", "춘장",
    "마요네즈", "케첩", "굴소스", "참치액", "액젓", "멸치액젓", "까나리액젓",
    "새우젓", "레몬즙", "오렌지즙", "매실액", "요리당", "미림", "소주", "연두",
    "유자청", "두유", "우유", "생크림", "요거트", "물엿", "올리고당", "꿀", "시럽",
    # 가루류
    "밀가루", "부침가루", "튀김가루", "전분", "녹말가루", "쌀가루", "빵가루",
    "고춧가루", "후춧가루", "후추", "흰후추", "통후추", "카레가루", "강황가루",
    "계피가루", "파슬리가루", "마늘가루", "양파가루", "베이킹파우더", "설탕", "소금",
    # 다진 것·씨앗
    "다진 마늘", "다진마늘", "다진 생강", "참깨", "검은깨", "들깨", "깨소금",
    "버터", "치즈", "마가린",
):
    _DISPLAY_UNIT.setdefault(_nm, ("작은술", 5.0))

# 한 줌(약 50g)이 자연스러운 나물·채소류
for _nm in ("숙주", "콩나물", "시금치", "미나리", "쑥갓", "부추", "쪽파", "달래",
            "취나물", "고사리", "어린잎채소", "새싹채소", "상추", "깻잎", "루꼴라"):
    _DISPLAY_UNIT.setdefault(_nm, ("줌", 50.0))

# 개수로 세는데 기존 표에 빠져 있던 재료 (영양·가격 계산에서도 0g이 되던 것들)
_EXTRA_PIECE = {
    "브로콜리": 250.0, "콜리플라워": 500.0, "파프리카": 150.0, "피망": 100.0,
    "단호박": 800.0, "애호박": 250.0, "가지": 150.0, "오이": 200.0,
    "닭가슴살": 100.0, "닭다리": 100.0,
    "유부": 10.0, "슬라이스햄": 20.0, "소시지": 30.0, "베이컨": 15.0,
    "새송이버섯": 50.0, "양송이버섯": 20.0, "팽이버섯": 150.0, "느타리버섯": 100.0,
    "레몬": 100.0, "라임": 60.0, "아보카도": 200.0, "키위": 100.0, "바나나": 120.0,
    "식빵": 35.0, "또띠아": 40.0, "김밥김": 2.0,
}
for _nm, _g in _EXTRA_PIECE.items():
    PIECE_GRAMS.setdefault(_nm, _g)
    _DISPLAY_UNIT.setdefault(_nm, ("개", _g))


# 고기·견과·건어물 등은 '큰술/줌/장'보다 '쪽·토막·컵'이 자연스럽다
# 고기는 1토막이 200g이라 식약처 1인분(30~50g)이면 '1/7토막'처럼 어색해진다.
# 덩어리 단위가 의미 없는 재료이므로 그램을 그대로 쓴다.
for _nm in ("아몬드", "호두", "땅콩", "잣", "캐슈넛", "피스타치오", "해바라기씨"):
    _DISPLAY_UNIT.setdefault(_nm, ("줌", 20.0))
for _nm in ("다시마", "김", "건미역", "미역"):
    _DISPLAY_UNIT.setdefault(_nm, ("장", 5.0))
for _nm in ("만두피", "라이스페이퍼", "춘권피", "식빵", "또띠아", "슬라이스치즈"):
    _DISPLAY_UNIT.setdefault(_nm, ("장", 10.0))
for _nm in ("즉석밥", "밥", "현미밥", "잡곡밥"):
    _DISPLAY_UNIT.setdefault(_nm, ("공기", 210.0))
for _nm in ("김치", "배추김치", "묵은지", "총각김치", "깍두기"):
    _DISPLAY_UNIT.setdefault(_nm, ("줌", 50.0))
for _nm in ("오징어", "주꾸미", "낙지", "문어"):
    _DISPLAY_UNIT.setdefault(_nm, ("마리", 200.0))
for _nm in ("대추", "곶감", "건포도", "크랜베리"):
    _DISPLAY_UNIT.setdefault(_nm, ("개", 5.0))
for _nm in ("바질", "파슬리", "로즈마리", "타임", "오레가노", "월계수잎", "고수"):
    _DISPLAY_UNIT.setdefault(_nm, ("장", 0.5))


# 부피로만 표기하는 재료 (무게·숟가락 단위가 어색한 것들)
_VOLUME_ONLY = {"물", "생수", "정수", "찬물", "따뜻한물", "끓는물", "얼음물"}


# [FIX] 단위마다 '쪼갤 수 있는 정도'가 다르다. 분모를 일률적으로 8까지
# 허용했더니 '4/5줌', '3/5쪽'처럼 가늠이 안 되는 표기가 나왔다.
#   계량스푼·컵  : 1/2·1/3·1/4 눈금이 실제로 있다       → 분모 4
#   덩어리       : 두부 1/4모, 양파 1/2개처럼 썰면 된다  → 분모 4
#   작은 낱개     : 마늘 2/3쪽 정도까지는 가늠이 된다      → 분모 3
#   세는 것       : 2/3마리, 3/5장은 말이 안 된다         → 분모 2 (반까지)
#   어림 단위     : '줌'은 손으로 집는 양이라 4/5가 무의미  → 분모 2
_UNIT_MAX_DENOM = {
    "큰술": 4, "작은술": 4, "스푼": 4, "컵": 4,
    "모": 4, "개": 4, "포기": 4, "통": 4, "공기": 4,
    "쪽": 3, "톨": 3, "알": 3,
    "마리": 2, "장": 2, "줄기": 2, "가닥": 2, "송이": 2, "봉지": 2,
    "캔": 2, "포": 2, "팩": 2, "토막": 2, "단": 2, "뿌리": 2, "대": 2, "조각": 2,
    "줌": 2, "꼬집": 2, "방울": 2,
}


def _fmt_fraction(f: Fraction) -> str:
    """Fraction → '2/3', '1', '1+1/2' 형태 문자열."""
    if f.denominator == 1:
        return str(f.numerator)
    whole, rem = divmod(f.numerator, f.denominator)
    frac = f"{rem}/{f.denominator}"
    return f"{whole}+{frac}" if whole else frac


def to_cooking_unit(standard_nm: str, amount_g: float) -> Optional[str]:
    """g을 조리 단위로 환산. 깔끔하게 떨어지지 않으면 None.

    '깔끔하다'의 기준:
      · 분모가 4 이하 (1/4, 1/3, 1/2, 2/3, 3/4, 1, 1+1/2 …)
      · 1/4 이상 (그보다 작으면 '0.1개'처럼 쓸모없는 값이 된다)
      · 반올림 오차가 12% 이내 (3g을 '1쪽'이라 하면 안 되므로)
    """
    if not standard_nm or not amount_g or amount_g <= 0:
        return None

    # [FIX] 물은 무게가 아니라 부피로 쓴다.
    # 식약처 원문이 '물 300ml(1½컵)'처럼 적혀 있어도 우리 화면에는
    # '300g'이나 '1/3작은술'로 나오고 있었다. 물 1g = 1ml 이므로
    # ml·L로 환산해 보여주고, 10ml 미만은 '약간'으로 쓴다.
    if standard_nm in _VOLUME_ONLY:
        if amount_g >= 1000:
            liters = amount_g / 1000
            return f"{liters:g}L"
        if amount_g >= 10:
            return f"{round(amount_g)}ml"
        return "약간"

    # 1g 미만은 어떤 단위로도 숫자가 의미 없다. 레시피에서도 '약간'으로 쓴다.
    if amount_g < 1.0:
        return "약간"
    hit = _DISPLAY_UNIT.get(standard_nm)
    if not hit:
        return None
    unit, per = hit
    if per <= 0:
        return None

    q = amount_g / per

    # 큰술로 올리면 더 자연스러운 경우 (간장 15g = 3작은술 → 1큰술)
    if unit == "작은술" and q >= 3:
        unit, per, q = "큰술", 15.0, amount_g / 15.0

    # 단위별로 허용 분모를 달리한다 (위 _UNIT_MAX_DENOM 참고)
    max_denom = _UNIT_MAX_DENOM.get(unit, 4)
    f = Fraction(q).limit_denominator(max_denom)
    if f < Fraction(1, max_denom):
        return None
    # [FIX] 오차를 비율로만 보면 소량 재료가 전부 걸러진다.
    #   소금 2g ÷ 작은술 5g = 0.4 → 1/3작은술(1.67g), 비율 오차 17% → 거부
    # 하지만 요리에서 소금 2g과 1/3작은술은 사실상 같은 양이다.
    # 비율 오차 15% 이내이거나, 절대 오차가 1g 이하면 인정한다.
    err_g = abs(float(f) - q) * per
    if abs(float(f) - q) > q * 0.15 and err_g > 1.0:
        return None
    # 대분수(3+1/3마리)는 오히려 읽기 어렵다. 1 미만 분수이거나 정수일 때만 쓴다.
    if f.denominator != 1 and f > 1:
        return None
    return f"{_fmt_fraction(f)}{unit}"


def _servings_by_energy(row: Dict, ingredients: List[Dict]) -> Optional[float]:
    """재료 열량 합 ÷ 1인분 열량(INFO_ENG)으로 인분 수를 구한다.

    [FIX] INFO_WGT(1인분 중량)는 1,156건 중 285건(24.7%)에만 들어 있다.
    반면 INFO_ENG(1인분 열량)는 거의 모든 레시피에 있고, 재료별 영양
    커버리지도 95.3%라 이 방식이 훨씬 넓게 적용된다.

    열량은 Atwater 계수로 계산한다 (탄수화물·단백질 4kcal/g, 지방 9kcal/g).
    무게(INFO_WGT)와 달리 조리 중 수분 증발·첨가에 영향을 받지 않아
    국물요리에서도 비교적 안정적이다.
    """
    info_eng = _n(row.get("INFO_ENG"))
    if info_eng <= 0:
        return None
    total = 0.0
    for ing in ingredients:
        carb = float(ing.get("carb_g", 0.0) or 0.0)
        prot = float(ing.get("protein_g", 0.0) or 0.0)
        fat  = float(ing.get("fat_g", 0.0) or 0.0)
        total += 4 * carb + 4 * prot + 9 * fat
    if total <= 0:
        return None
    return total / info_eng


def _servings_by_weight(row: Dict, ingredients: List[Dict]) -> Optional[float]:
    """재료 총중량 ÷ 1인분 중량(INFO_WGT). 값이 있는 레시피에만 쓸 수 있다."""
    serving_g = _n(row.get("INFO_WGT"))
    total_g = sum(float(i.get("amount_g", 0.0) or 0.0) for i in ingredients)
    if serving_g <= 0 or total_g <= 0:
        return None
    return total_g / serving_g


def _estimate_servings(row: Dict, ingredients: List[Dict]) -> Optional[int]:
    """재료 분량이 몇 인분인지 역산. 근거가 약하면 None.

    실측(1,156건) 결과 INFO_WGT를 가진 레시피는 285건(24.7%)뿐이고,
    역산값에도 잡음이 있다. 10인분 이상이 19건, 47인분이 1건 나왔는데
    실제로 그런 레시피는 없다. INFO_WGT 자체가 부정확한 경우가 섞여 있다.
      예) 곤약잡채 INFO_WGT=45g → 잡채 1인분이 45g일 수 없다

    또 INFO_WGT는 '완성된 요리' 중량이고 재료합은 '조리 전' 값이라
    국물요리는 물이 더해져 늘고, 김치·나물은 수분이 빠져 줄어든다.

    그래서 **1~4인분 범위로 떨어질 때만** 표시한다. 그 밖은 역산이
    빗나간 것으로 보고 아무것도 보여주지 않는다. 틀린 인분 수를 적는 것은
    표시하지 않는 것보다 나쁘다.
    """
    # 열량 기준을 먼저 쓰고, 안 되면 중량 기준으로 넘어간다
    ratio = _servings_by_energy(row, ingredients)
    if ratio is None:
        ratio = _servings_by_weight(row, ingredients)
    if ratio is None:
        return None

    n = round(ratio)
    if not (1 <= n <= 4):
        return None
    # 반올림 오차가 크면(예: 1.45 → 1) 신뢰할 수 없다
    if abs(ratio - n) > 0.35:
        return None
    return n


def _is_valid_ingredient_name(standard_nm: str) -> bool:
    if not standard_nm:
        return False
    nm = standard_nm.strip()
    if nm in _NON_INGREDIENT_EXACT:
        return False
    if "인분" in nm:          # "2인분 기준" 등 분량 안내
        return False
    if len(nm) >= 2:
        return True
    return nm in _SINGLE_CHAR_INGREDIENTS


def _parse_ingredients(parts_text: str) -> List[Dict]:
    if not parts_text:
        return []

    # <br> 태그 줄바꿈 처리 후 파싱
    text = parts_text.replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    ingredients = []

    # [FIX] 식약처 원문의 [재료]·[양념] 같은 섹션명을 그냥 지우고 있었다.
    # 우리의식탁·만개의레시피 등은 '기본 재료 / 양념장 재료'로 묶어 보여주는데,
    # 그 정보가 원문에 있는데도 버려서 한 덩어리로만 나열됐다.
    # 섹션명을 각 재료에 section 필드로 붙여 화면에서 묶을 수 있게 한다.
    section = ""

    for line in lines:
        # 불릿 제거
        line = re.sub(r"^[●•·]\s*", "", line).strip()
        # 대괄호 섹션명은 기억해 두고 본문에서는 제거
        for sec in re.findall(r"\[(.*?)\]", line):
            sec = sec.strip()
            if sec:
                section = sec
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
                "section":                section,
                # 조리 단위로 깔끔하게 떨어질 때만 값이 들어간다 (아니면 None)
                "amount_display":         to_cooking_unit(standard_nm, amount_g),
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


async def _enrich_ingredient(ing: Dict, allow_ai: bool = True) -> Dict:
    try:
        nutrition_info, price_info = await asyncio.gather(
            nutrition_service.get_nutrition_for_ingredient(
                ing.get("standard_nm", ""),
                float(ing.get("amount_g", 0.0) or 0.0),
                allow_ai=allow_ai,
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


async def _enrich_ingredients(ingredients: List[Dict], allow_ai: bool = True) -> List[Dict]:
    if not ingredients:
        return []

    # [FIX] 재료마다 각각 Gemini를 부르면 레시피 하나에 재료 개수만큼(N번)
    # API 호출이 발생함. 로컬/캐시에 없는 재료명을 먼저 모아서 딱 한 번의
    # 배치 요청으로 채워놓은 뒤, 개별 enrich는 캐시에서 즉시 읽어가게 함.
    if allow_ai:
        missing = [
            ing.get("standard_nm", "")
            for ing in ingredients
            if ing.get("standard_nm") and not nutrition_service.has_local_or_cached(ing["standard_nm"])
        ]
        if missing:
            await nutrition_service.estimate_nutrition_batch(missing)

    tasks = [_enrich_ingredient(dict(ing), allow_ai) for ing in ingredients]
    return await asyncio.gather(*tasks)


def _safe_json(resp: httpx.Response, label: str) -> Dict:
    try:
        return resp.json()
    except Exception as e:
        print(f"[{label}] JSON 파싱 실패: {e}, status={resp.status_code}")
        return {}


async def _format(row: Dict, allow_ai: bool = True) -> Dict:
    # [FIX] 식약처 COOKRCP01은 MANUAL01~20과 짝을 이루는 MANUAL_IMG01~20
    # (단계별 사진 URL)을 함께 제공하는데 기존 코드가 이를 버리고 있었다.
    # 조리 순서가 텍스트만 나와서 따라하기 어렵다는 피드백에 대한 대응.
    steps = []
    for i in range(1, 21):
        desc = (row.get(f"MANUAL{i:02d}") or "").replace("\\n", "\n").strip()
        img  = (row.get(f"MANUAL_IMG{i:02d}") or "").strip()
        if desc:
            steps.append({"step": i, "desc": desc, "img_url": img})

    ingredients = _parse_ingredients(row.get("RCP_PARTS_DTLS", ""))
    ingredients = await _enrich_ingredients(ingredients, allow_ai)

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
        # [FIX] 재료비가 '몇 인분'인지 알 수 없는 문제에 대한 대응.
        #
        # 식약처 영양정보(INFO_ENG 등)는 1인분 기준인데, price_total_krw는
        # RCP_PARTS_DTLS(재료 목록)를 그대로 합산한 값이다. 재료 목록이 몇 인분인지는
        # 레시피마다 다른데(캐시 1,142건 측정: 중앙값 240g, 최대 4,940g),
        # 추천 점수는 이 둘을 같은 축에서 비교하고 있다.
        #
        # 1인분으로 환산하려면 1인분 중량(INFO_WGT)이 필요한데, 식약처 API가
        # 이 필드를 빈 값("")으로 내려준다(50건 전수 확인). 따라서 환산할 근거가 없다.
        # 근거 없는 추정치를 점수에 넣는 대신, 재료 총 중량을 함께 노출해
        # 사용자가 "이 금액이 어느 정도 분량에 대한 것인지" 판단할 수 있게 한다.
        "total_ingredient_g": round(
            sum(float(ing.get("amount_g", 0.0) or 0.0) for ing in ingredients), 1
        ),
        # [FIX] 재료 분량이 몇 인분인지 표시하기 위한 값.
        #
        # 식약처 INFO_WGT(1인분 완성 중량)가 있는 레시피에 한해
        # '재료 총중량 ÷ 1인분 중량'으로 역산한다. 값이 없으면 None이고,
        # 화면에서는 인분 표시를 생략한다(추정으로 적으면 틀린 정보가 된다).
        #
        # 주의: INFO_WGT는 '완성된 요리' 기준이고 재료 총중량은 '조리 전'이라
        # 국물요리는 물이 더해지고 구이는 수분이 날아가 오차가 있다. 추정값이다.
        "servings": _estimate_servings(row, ingredients),   # 영양 enrich 이후에 계산됨
        "errors": []
    }


def _row_to_summary(r: Dict) -> Dict:
    return {
        "id":        str(r.get("RCP_SEQ") or ""),
        "name":      str(r.get("RCP_NM") or ""),
        "category":  r.get("RCP_PAT2") or "기타",
        "method":    r.get("RCP_WAY2") or "기타",
        "calories":  _n(r.get("INFO_ENG")),
        "image_url": r.get("ATT_FILE_NO_MAIN") or "",
        "tags":      []
    }


async def _fetch_by_url(client: httpx.AsyncClient, url: str, label: str) -> List[Dict]:
    try:
        resp = await client.get(url)
        data = _safe_json(resp, label)
        return data.get("COOKRCP01", {}).get("row", [])
    except Exception as e:
        print(f"[search_recipes/{label} 오류] {e}")
        return []


async def search_recipes(query: str) -> List[Dict]:
    print(f"[search_recipes] MFDS_API_KEY length={len(MY_API_KEY)}")
    if not MY_API_KEY:
        return []

    # ── #1 Fix: 이름 검색 + 재료 검색을 동시에 수행 ──────────────────────
    # RCP_NM=query  → 레시피 이름에 검색어 포함 (예: "토마토 파스타")
    # RCP_PARTS_DTLS=query → 재료 목록에 검색어 포함 (예: 방울토마토가 들어간 레시피)
    # 두 결과를 합산하면 "토마토" 검색 시 "방울토마토" 재료 레시피도 나온다.
    async with httpx.AsyncClient(timeout=15) as client:
        if query:
            name_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/100/RCP_NM={quote(query)}"
            ing_url  = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/100/RCP_PARTS_DTLS={quote(query)}"
            print(f"[search_recipes] name_url={name_url}")
            print(f"[search_recipes] ing_url={ing_url}")
            name_rows, ing_rows = await asyncio.gather(
                _fetch_by_url(client, name_url, "name"),
                _fetch_by_url(client, ing_url,  "ingredient"),
            )
            # 중복 제거: RCP_SEQ 기준, 이름 검색 결과 우선
            seen: set[str] = set()
            rows: List[Dict] = []
            for r in name_rows + ing_rows:
                seq = str(r.get("RCP_SEQ") or "")
                if seq and seq not in seen:
                    seen.add(seq)
                    rows.append(r)
        else:
            # 빈 검색 → 전체 추천용
            browse_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/100"
            print(f"[search_recipes] browse_url={browse_url}")
            rows = await _fetch_by_url(client, browse_url, "browse")

        result = []
        for r in rows:
            _save_to_cache(r)
            result.append(_row_to_summary(r))

        print(f"[recipe_service] search 결과 {len(result)}건, 캐시 {len(RECIPE_CACHE)}건")
        return result


async def get_recipe_detail(recipe_id: str, name: str = None,
                            allow_ai: bool = True) -> Optional[Dict]:
    recipe_id = str(recipe_id)
    cached = RECIPE_CACHE.get(recipe_id)
    if cached:
        print(f"[recipe_service] 캐시 적중: {recipe_id}")
        return await _format(cached, allow_ai)

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
                        return await _format(r, allow_ai)
                for r in rows:
                    if (r.get("RCP_NM") or "").strip() == name.strip():
                        return await _format(r, allow_ai)

            id_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/1/RCP_SEQ={recipe_id}"
            res    = await client.get(id_url)
            data   = _safe_json(res, "detail_by_id")
            rows   = data.get("COOKRCP01", {}).get("row", [])
            if rows:
                r = rows[0]
                _save_to_cache(r)
                if str(r.get("RCP_SEQ") or "") == recipe_id:
                    return await _format(r, allow_ai)

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