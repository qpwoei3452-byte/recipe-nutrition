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
    s = (name or "").strip()

    for compound, mapped in _COMPOUND_SORTED:
        if compound == s or s.startswith(compound) or s.endswith(compound):
            return mapped
        normalized_key = compound.replace(" ", "")
        normalized_s   = s.replace(" ", "")
        if normalized_key in normalized_s and len(compound) >= 3:
            return mapped

    s = re.sub(r"^[●•·]\s*", "", s)
    s = re.sub(r"^(주재료|부재료|소스|양념|재료)\s*[:：]?\s*", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\d+(?:\.\d+)?\s*(kg|g|mg|ml|l|개|큰술|작은술|컵|모|뿌리|토막|마리|장|쪽|포기|단|줄기|알|송이|봉지)", " ", s, flags=re.I)
    s = re.sub(r"\d+\s*/\s*\d+\s*개", " ", s)
    s = re.sub(r"(적당량|약간|조금|소량)", "", s)
    s = re.sub(r"[^\w가-힣]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    for a in _ALIASES:
        if a in s:
            return a

    return s


def _extract_amount_g(text: str, ingredient_name: str) -> float:
    s = text or ""

    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", s, re.I)
    if m:
        return float(m.group(1)) * 1000

    m = re.search(r"(\d+(?:\.\d+)?)\s*g(?!\w)", s, re.I)
    if m:
        return float(m.group(1))

    m = re.search(r"(\d+(?:\.\d+)?)\s*mg", s, re.I)
    if m:
        return float(m.group(1)) / 1000

    m = re.search(r"(\d+(?:\.\d+)?)\s*ml", s, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*[lL](?!\w)", s)
    if m:
        return float(m.group(1)) * 1000

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:큰술|스푼|tbsp)", s, re.I)
    if m:
        return float(m.group(1)) * 15.0

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:작은술|티스푼|tsp)", s, re.I)
    if m:
        return float(m.group(1)) * 5.0

    m = re.search(r"(\d+(?:\.\d+)?)\s*컵", s)
    if m:
        return float(m.group(1)) * 200.0

    for unit, unit_map in KOREAN_UNIT_GRAMS.items():
        m = re.search(rf"(\d+)\s*/\s*(\d+)\s*{unit}", s)
        if m:
            num, den = float(m.group(1)), float(m.group(2))
            if den > 0:
                gram = unit_map.get(ingredient_name) or unit_map.get("default", 100.0)
                return (num / den) * gram
        m = re.search(rf"(\d+(?:\.\d+)?)\s*{unit}", s)
        if m:
            count = float(m.group(1))
            gram  = unit_map.get(ingredient_name) or unit_map.get("default", 100.0)
            return count * gram

    m = re.search(r"(\d+)\s*/\s*(\d+)\s*개", s)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if den > 0:
            return (num / den) * PIECE_GRAMS.get(ingredient_name, 0.0)

    m = re.search(r"(\d+(?:\.\d+)?)\s*개", s)
    if m:
        return float(m.group(1)) * PIECE_GRAMS.get(ingredient_name, 0.0)

    m = re.search(r"(\d+(?:\.\d+)?)\s*$", s.strip())
    if m:
        return float(m.group(1))

    return 0.0


def _split_chunks(line: str) -> List[str]:
    chunks = [c.strip() for c in re.split(r",|·|•", line) if c.strip()]
    return chunks if chunks else [line.strip()]


_SINGLE_CHAR_INGREDIENTS = {
    "굴", "무", "파", "배", "콩", "김", "잣", "깨", "엿", "술", "쑥", "게",
    "쌀", "밥", "떡", "팥", "밤",
    "햄",
    "꿀", "마", "감", "차",
    "물",
}


_NON_INGREDIENT_EXACT = {
    "기준", "재료", "주재료", "부재료", "소스", "양념", "고명",
    "장식", "준비", "필수", "선택", "곁들임", "토핑",
}


from fractions import Fraction

_EYE_MEASURE = {
    "양파": 170.0, "당근": 150.0, "대파": 140.0, "마늘": 5.0, "생강": 5.0,
}
PIECE_GRAMS.update(_EYE_MEASURE)
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
for _nm, _g in PIECE_GRAMS.items():
    _DISPLAY_UNIT.setdefault(_nm, ("개", _g))
_DISPLAY_UNIT["대파"] = ("대", 140.0)
_DISPLAY_UNIT["마늘"] = ("쪽", 5.0)
_DISPLAY_UNIT["생강"] = ("톨", 5.0)
_DISPLAY_UNIT["무"]   = ("토막", 150.0)
for _nm in (
    "간장", "국간장", "진간장", "저염간장", "참기름", "들기름", "식용유", "올리브유",
    "포도씨유", "식초", "맛술", "청주", "된장", "고추장", "쌈장", "춘장",
    "마요네즈", "케첩", "굴소스", "참치액", "액젓", "멸치액젓", "까나리액젓",
    "새우젓", "레몬즙", "오렌지즙", "매실액", "요리당", "미림", "소주", "연두",
    "유자청", "두유", "우유", "생크림", "요거트", "물엿", "올리고당", "꿀", "시럽",
    "밀가루", "부침가루", "튀김가루", "전분", "녹말가루", "쌀가루", "빵가루",
    "고춧가루", "후춧가루", "후추", "흰후추", "통후추", "카레가루", "강황가루",
    "계피가루", "파슬리가루", "마늘가루", "양파가루", "베이킹파우더", "설탕", "소금",
    "다진 마늘", "다진마늘", "다진 생강", "참깨", "검은깨", "들깨", "깨소금",
    "버터", "치즈", "마가린",
):
    _DISPLAY_UNIT.setdefault(_nm, ("작은술", 5.0))

for _nm in ("숙주", "콩나물", "시금치", "미나리", "쑥갓", "부추", "쪽파", "달래",
            "취나물", "고사리", "어린잎채소", "새싹채소", "상추", "깻잎", "루꼴라"):
    _DISPLAY_UNIT.setdefault(_nm, ("줌", 50.0))

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

_VOLUME_ONLY = {"물", "생수", "정수", "찬물", "따뜻한물", "끓는물", "얼음물"}

_UNIT_MAX_DENOM = {
    "큰술": 4, "작은술": 4, "스푼": 4, "컵": 4,
    "모": 4, "개": 4, "포기": 4, "통": 4, "공기": 4,
    "쪽": 3, "톨": 3, "알": 3,
    "마리": 2, "장": 2, "줄기": 2, "가닥": 2, "송이": 2, "봉지": 2,
    "캔": 2, "포": 2, "팩": 2, "토막": 2, "단": 2, "뿌리": 2, "대": 2, "조각": 2,
    "줌": 2, "꼬집": 2, "방울": 2,
}


def _fmt_fraction(f: Fraction) -> str:
    if f.denominator == 1:
        return str(f.numerator)
    whole, rem = divmod(f.numerator, f.denominator)
    frac = f"{rem}/{f.denominator}"
    return f"{whole}+{frac}" if whole else frac


def to_cooking_unit(standard_nm: str, amount_g: float) -> Optional[str]:
    if not standard_nm or not amount_g or amount_g <= 0:
        return None

    if standard_nm in _VOLUME_ONLY:
        if amount_g >= 1000:
            liters = amount_g / 1000
            return f"{liters:g}L"
        if amount_g >= 10:
            return f"{round(amount_g)}ml"
        return "약간"

    if amount_g < 1.0:
        return "약간"
    hit = _DISPLAY_UNIT.get(standard_nm)
    if not hit:
        return None
    unit, per = hit
    if per <= 0:
        return None

    q = amount_g / per

    if unit == "작은술" and q >= 3:
        unit, per, q = "큰술", 15.0, amount_g / 15.0

    max_denom = _UNIT_MAX_DENOM.get(unit, 4)
    f = Fraction(q).limit_denominator(max_denom)
    if f < Fraction(1, max_denom):
        return None
    err_g = abs(float(f) - q) * per
    if abs(float(f) - q) > q * 0.15 and err_g > 1.0:
        return None
    if f.denominator != 1 and f > 1:
        return None
    return f"{_fmt_fraction(f)}{unit}"


def _servings_by_energy(row: Dict, ingredients: List[Dict]) -> Optional[float]:
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
    serving_g = _n(row.get("INFO_WGT"))
    total_g = sum(float(i.get("amount_g", 0.0) or 0.0) for i in ingredients)
    if serving_g <= 0 or total_g <= 0:
        return None
    return total_g / serving_g


def _estimate_servings(row: Dict, ingredients: List[Dict]) -> Optional[int]:
    ratio = _servings_by_energy(row, ingredients)
    if ratio is None:
        ratio = _servings_by_weight(row, ingredients)
    if ratio is None:
        return None

    n = round(ratio)
    if not (1 <= n <= 4):
        return None
    if abs(ratio - n) > 0.35:
        return None
    return n


def _is_valid_ingredient_name(standard_nm: str) -> bool:
    if not standard_nm:
        return False
    nm = standard_nm.strip()
    if nm in _NON_INGREDIENT_EXACT:
        return False
    if "인분" in nm:
        return False
    if len(nm) >= 2:
        return True
    return nm in _SINGLE_CHAR_INGREDIENTS


def _parse_ingredients(parts_text: str) -> List[Dict]:
    if not parts_text:
        return []

    text = parts_text.replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    ingredients = []
    section = ""

    for line in lines:
        line = re.sub(r"^[●•·]\s*", "", line).strip()
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

            has_number = bool(re.search(r"\d", chunk))
            if has_number:
                amount_g = _extract_amount_g(chunk, standard_nm)
            else:
                if re.search(r"(약간|적당량|조금|소량)", chunk):
                    amount_g = 2.0
                else:
                    continue

            ingredients.append({
                "raw_name":               chunk,
                "section":                section,
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
    steps = []
    for i in range(1, 21):
        desc = (row.get(f"MANUAL{i:02d}") or "").replace("\\n", "\n").strip()
        img  = (row.get(f"MANUAL_IMG{i:02d}") or "").strip()
        if desc:
            steps.append({"step": i, "desc": desc, "img_url": img})

    ingredients = _parse_ingredients(row.get("RCP_PARTS_DTLS", ""))
    ingredients = await _enrich_ingredients(ingredients, allow_ai)

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
        "total_ingredient_g": round(
            sum(float(ing.get("amount_g", 0.0) or 0.0) for ing in ingredients), 1
        ),
        "servings": _estimate_servings(row, ingredients),
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

    async with httpx.AsyncClient(timeout=30) as client:
        if query:
            name_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/1000/RCP_NM={quote(query)}"
            ing_url  = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/1000/RCP_PARTS_DTLS={quote(query)}"
            print(f"[search_recipes] name_url={name_url}")
            print(f"[search_recipes] ing_url={ing_url}")
            name_rows, ing_rows = await asyncio.gather(
                _fetch_by_url(client, name_url, "name"),
                _fetch_by_url(client, ing_url,  "ingredient"),
            )
            seen: set[str] = set()
            rows: List[Dict] = []
            for r in name_rows + ing_rows:
                seq = str(r.get("RCP_SEQ") or "")
                if seq and seq not in seen:
                    seen.add(seq)
                    rows.append(r)
        else:
            # 빈 검색 → 전체 추천용 (100개, 속도 우선)
            browse_url = f"{BASE_URL}/{MY_API_KEY}/COOKRCP01/json/1/100"
            print(f"[search_recipes] browse_url={browse_url}")
            rows = await _fetch_by_url(client, browse_url, "browse")

        result = []
        for r in rows:
            _save_to_cache(r)
            result.append(_row_to_summary(r))

        print(f"[recipe_service] search 결과 {len(result)}건, 캐시 {len(RECIPE_CACHE)}건")
        return result


def get_recipe_for_scoring(recipe_id: str) -> Optional[Dict]:
    """추천 점수 계산용 경량 버전. _format() 없이 캐시에서 직접 추출.
    asyncio.gather 없이 동기 list comprehension으로 처리 → 타임아웃 방지."""
    cached = RECIPE_CACHE.get(str(recipe_id))
    if not cached:
        return None

    # 알레르기 필터용 간이 재료 파싱 (RCP_PARTS_DTLS 텍스트에서 이름만 추출)
    raw_parts = cached.get("RCP_PARTS_DTLS") or ""
    simple_ingredients: List[Dict] = []
    for chunk in re.split(r"[\n,·•]", raw_parts):
        chunk = chunk.strip()
        if not chunk:
            continue
        chunk = re.sub(r"\([^)]*\)", "", chunk)
        chunk = re.sub(r"\d+(?:\.\d+)?\s*(?:g|ml|kg|l|개|큰술|작은술|컵|모|뿌리|토막|마리|장|쪽|포기|단|줄기|알|송이|봉지|약간|적당량)", "", chunk, flags=re.I)
        chunk = re.sub(r"[^\w가-힣]", " ", chunk).strip()
        words = chunk.split()
        name_candidate = words[0] if words else ""
        if name_candidate and len(name_candidate) >= 1:
            simple_ingredients.append({"name": name_candidate, "standard_nm": name_candidate})

    return {
        "id":            str(cached.get("RCP_SEQ") or ""),
        "name":          str(cached.get("RCP_NM") or ""),
        "category":      cached.get("RCP_PAT2") or "기타",
        "method":        cached.get("RCP_WAY2") or "기타",
        "image_url":     cached.get("ATT_FILE_NO_MAIN") or "",
        "ingredients":   simple_ingredients,
        "price_total_krw":  0.0,
        "price_estimated":  True,
        "nutrition_total": {
            "energy_kcal": _n(cached.get("INFO_ENG")),
            "protein_g":   _n(cached.get("INFO_PRO")),
            "fat_g":       _n(cached.get("INFO_FAT")),
            "carb_g":      _n(cached.get("INFO_CAR")),
            "sodium_mg":   _n(cached.get("INFO_NA")),
            "sugar_g":     0.0,
            "fiber_g":     0.0,
            "calcium_mg":  0.0,
            "total_g":     _n(cached.get("INFO_WGT")),
        },
        "cook_time_min":        30,
        "steps":                [],
        "source":               "식약처",
        "errors":               [],
        "total_ingredient_g":   0.0,
        "servings":             None,
        "raw_ingredients_text": raw_parts,
    }


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