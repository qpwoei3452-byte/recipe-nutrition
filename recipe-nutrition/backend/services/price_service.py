"""
price_service.py — 규칙 기반 파이프라인 (Gemini 검증 없음)

Gemini를 제거하고 규칙 기반으로만 처리:
  → 빠름 (4.5초 대기 없음)
  → 안정적 (API 실패 없음)
  → 현실적 (재료별 상한선으로 이상값 차단)

파이프라인:
  1) 가격 캐시 히트 → 즉시 반환
  2) 재료명 정규화 (정규식 + 룩업 테이블)
  3) 무료 재료 → 0원
  4) KAMIS 조회 → 성공 시 상한선 체크 후 반환
  5) 네이버 쇼핑 조회 → 상한선 체크 후 반환 or STANDARD_AVERAGE
  6) STANDARD_AVERAGE → 최후 수단
"""

import asyncio
import json
import os
import re
import time
from difflib import get_close_matches
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

import httpx


# ─────────────────────────────────────────────────────────────
# 환경변수
# ─────────────────────────────────────────────────────────────
def _load_env_file() -> dict:
    env = {}
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return env
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


_ENV = _load_env_file()

KAMIS_KEY    = (os.getenv("KAMIS_API_KEY") or _ENV.get("KAMIS_API_KEY", "")).strip()
KAMIS_ID     = (os.getenv("KAMIS_API_ID")  or _ENV.get("KAMIS_API_ID",  "")).strip()
KAMIS_URL    = "https://www.kamis.or.kr/service/price/xml.do"

NAVER_ID     = (os.getenv("NAVER_CLIENT_ID")     or _ENV.get("NAVER_CLIENT_ID",     "")).strip()
NAVER_SECRET = (os.getenv("NAVER_CLIENT_SECRET") or _ENV.get("NAVER_CLIENT_SECRET", "")).strip()
NAVER_URL    = "https://openapi.naver.com/v1/search/shop.json"

CATEGORY_CODES = ["100", "200", "300", "400", "500", "600"]

# 캐시 파일 경로
_CACHE_DIR        = Path(__file__).parent / "cache"
_PRICE_CACHE_FILE = _CACHE_DIR / "ingredient_price_cache.json"
_CACHE_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────
# 표준 평균가 DB (STANDARD_AVERAGE)
# ─────────────────────────────────────────────────────────────
STANDARD_AVERAGE_DB: Dict[str, float] = {
    # 채소 (원/100g)
    "배추": 150,    "양배추": 200,  "양파": 300,    "대파": 350,
    "파": 350,      "마늘": 700,    "생강": 800,    "시금치": 600,
    "부추": 600,    "상추": 500,    "깻잎": 1200,   "쑥갓": 800,
    "숙주": 300,    "콩나물": 250,  "당근": 400,    "감자": 300,
    "고구마": 300,  "애호박": 500,  "오이": 450,    "가지": 600,
    "무": 150,      "토마토": 700,  "방울토마토": 1000, "브로콜리": 900,
    "컬리플라워": 1200, "미나리": 700, "도라지": 1500, "연근": 1200,
    "버섯": 700,    "표고버섯": 1500, "팽이버섯": 400, "새송이버섯": 800,
    "느타리버섯": 600, "고추": 800, "청양고추": 1000, "쑥": 800,
    "냉이": 2000,   "봄동": 400,    "치커리": 600,  "양상추": 500,
    "로메인": 500,  "깻잎순": 1200, "쪽파": 600,    "대추": 2000,
    "비트": 800,    "연근": 1200,   "우엉": 800,    "피망": 600,
    "파프리카": 800, "홍파프리카": 800, "황파프리카": 800, "청파프리카": 600,
    # 과일
    "사과": 700,    "배": 800,      "딸기": 2000,   "귤": 600,
    "오렌지": 1000, "포도": 1500,   "복숭아": 1500, "수박": 300,
    "블루베리": 3000, "자두": 1500, "멜론": 800,    "석류": 1000,
    "자몽": 1500,   "레몬": 2000,   "크랜베리": 1500,
    # 두부·가공식품
    "두부": 500,    "순두부": 450,  "곤약": 600,    "실곤약": 400,
    "어묵": 550,    "맛살": 500,    "만두피": 600,  "김치": 450,
    "콩비지": 300,  "두유": 300,
    # 액체 조미료
    "간장": 350,    "액젓": 500,    "멸치액젓": 500, "새우젓": 800,
    "참기름": 1200, "들기름": 1800, "식용유": 200,  "올리브유": 1500,
    "올리브오일": 1500, "식초": 250, "청주": 400,   "맛술": 500,
    "요리당": 600,  "발사믹식초": 1500, "발사믹소스": 1500,
    "발사믹크레마": 3000, "매실액": 800, "유자청": 1500,
    "화이트와인": 2000, "레몬즙": 2000, "오렌지즙": 1500,
    "석류즙": 2000, "꿀": 1200,
    # 분말·고체 조미료
    "고춧가루": 1800, "된장": 500,  "고추장": 600,  "쌈장": 700,
    "머스터드": 1000, "마요네즈": 600, "케첩": 400,
    # 달걀·유제품
    "달걀": 400,    "계란": 400,    "우유": 200,    "생크림": 1200,
    "버터": 2500,   "치즈": 2000,   "모짜렐라": 2000, "플레인요거트": 800,
    "요거트": 800,  "슬라이스치즈": 1500,
    # 육류
    "돼지고기": 2000, "소고기": 4000, "닭고기": 1000, "닭가슴살": 1200,
    "삼겹살": 2500,  "베이컨": 2500, "소시지": 800,  "스팸": 1800,
    "통조림 햄": 2000, "햄": 1500,
    # 해산물
    "새우": 2500,   "오징어": 1800, "꼬막": 2500,   "바지락": 1800,
    "조개": 1800,   "멸치": 1500,   "황태": 3000,   "대구": 2000,
    "굴": 3000,     "꽁치": 1500,   "삼치": 2000,   "도미": 3000,
    "황태채": 3000, "북어채": 3000, "메추리알": 1500, "낙지": 3000,
    "주꾸미": 3000, "문어": 4000,
    # 곡류·면
    "쌀": 250,      "현미": 300,    "찹쌀": 400,    "밀가루": 150,
    "소면": 300,    "당면": 400,    "메밀면": 700,  "떡": 600,
    "쌀국수": 600,
    # 견과·씨앗
    "잣": 5000,     "호두": 4000,   "아몬드": 3000, "땅콩": 1000,
    "참깨": 1500,   "깨": 1500,     "해바라기씨": 800, "호박씨": 1000,
    "검은콩": 900,  "강낭콩": 900,
    # 기타 자주 쓰이는 재료
    "설탕": 100,    "물엿": 300,    "산마": 5000,   "부침가루": 200,
    "날콩가루": 1500, "콩가루": 1000, "가시오가피": 3000,
    "다시마": 2000, "함초": 3000,   "미역": 1500,   "건미역": 3000,
    "가지": 600,    "돌나물": 500,  "녹말": 500,    "식용꽃": 3000,
    "들깨가루": 1500, "들깻가루": 1500, "참나물": 1500,
    "모시조개": 2000, "바지락": 1800, "국간장": 400,
    "드레싱 올리브오일": 2000, "올리브오일": 1500,
    # 해산물 추가
    "꼬막": 1800,   "달래": 1500,   "골뱅이": 2000, "전복": 6000,
    "홍합": 1500,   "낙지": 2500,   "주꾸미": 2500, "문어": 3000,
    # 기타 누락 재료
    "풋마늘": 500,  "건오징어": 3000, "포항초": 800, "순무": 500,
    "강화순무": 500, "참치": 2000,  "통조림 참치": 2000,
    # 육수류 (비비고 사골곰탕 500g 약 2,000원 기준 → 100g당 400원)
    "사골육수": 400,  "멸치육수": 200,  "다시마육수": 150,
    "채소육수": 200,  "닭육수": 300,    "한우육수": 500,  "육수": 300,
    # 채소 추가
    "단호박": 600,    "호박": 500,      "늙은호박": 400,
    # 육류 추가
    "삼겹살": 2500,   "목살": 2000,     "항정살": 3000,   "월계수잎": 500,
    # 빵·베이킹
    "베이글": 1500,   "식빵": 800,      "이스트": 1000,
    "블루베리 발효원종": 3000,
    # 음료류
    "맥주": 400,      "소주": 200,      "막걸리": 300,
    "화이트와인": 2000, "레드와인": 2000,
    # 채소 추가
    "어린잎채소": 1000, "베이비채소": 1000,
    # 기름 추가
    "튀김기름": 200,
    # 떡류
    "증편": 1600,    "가래떡": 800,
    # 소스류
    "칠리소스": 800,  "토마토소스": 600, "크림소스": 1200,
    # 기타
    "망고": 3000,    "견과류": 3000,   "빵가루": 400,
    "뽕잎가루": 2500, "모차렐라치즈": 2500,
    "슈레드 모차렐라치즈": 2500, "배추": 150,
    "블랙올리브": 800,  "그린올리브": 800,  "해조국수": 2500,
    "곤약면": 600,      "밥": 150,          "쌀밥": 150,
    # 소고기 부위
    "안심": 8000,    "등심": 7000,   "채끝": 7000,   "갈비": 6000,
    "양지": 4000,    "불고기": 4000,
    # 조미료
    "올리고당": 300,  "물엿": 300,    "아가베시럽": 800,
    # 허브류
    "애플민트": 1500, "바질": 1500,   "로즈메리": 1500,
    "파슬리": 1200,  "딜": 1500,
    # 과일
    "블루베리": 3000, "망고": 3000, "바나나": 700,
    # 돼지고기 부위
    "족발": 2500,    "보쌈": 2000,
    # 밀가루 종류
    "박력분": 200,   "강력분": 200,  "중력분": 150,
    # 즉석밥 (햇반 210g = 2,800원 기준 → 100g당 1,333원)
    "즉석밥": 1333,  "햇반": 1333,
    # 통조림류
    "후르츠칵테일": 400, "과일통조림": 400, "복숭아통조림": 400,
    # 대체감미료
    "알룰로스": 600,  "에리스리톨": 800, "자일리톨": 1200,
    # 해산물
    "백합": 2500,    "모시조개": 2000,   "재첩": 2500,
    # 채소
    "토란": 600,     "우엉": 700,        "연근": 1000,
    # 해조류
    "미역줄기": 400, "미역": 800,
    # 발효원종 (500g 약 6,000원 기준)
    "발효원종": 1200,
    # 기타
    "묵은지": 450,
    # 해산물 추가
    "대하": 3000,     "아보카도": 2000,
    # 건재료
    "대추": 2000,     "건대추": 2000,   "인삼": 4000,
    "검은콩": 900,    "불린 검은콩": 900,
}


# ─────────────────────────────────────────────────────────────
# 재료별 100g당 가격 상한선
# 이 값을 초과하면 네이버 결과를 버리고 STANDARD_AVERAGE 사용
# ─────────────────────────────────────────────────────────────
PRICE_CAP: Dict[str, float] = {
    # 물/기본 재료 (거의 0원)
    "물": 100,      "쌀뜨물": 100,  "생수": 100,    "탄산수": 100,
    "얼음": 100,
    # 채소 (100g당 최대)
    "배추": 600,    "양배추": 600,  "양파": 800,    "대파": 800,
    "파": 800,      "마늘": 2000,   "시금치": 2000, "숙주": 600,
    "콩나물": 600,  "당근": 1200,   "감자": 800,    "고구마": 800,
    "애호박": 1200, "오이": 1000,   "무": 500,      "가지": 1500,
    "토마토": 2000, "방울토마토": 3000, "브로콜리": 2000,
    "고추": 2000,   "청양고추": 2000, "비트": 3000, "파프리카": 2000,
    "피망": 1500,   "치커리": 1500, "양상추": 1500, "상추": 1500,
    "깻잎": 3000,
    # 과일
    "사과": 2000,   "배": 2500,     "딸기": 5000,   "귤": 1500,
    "오렌지": 2500, "블루베리": 8000, "석류": 5000, "레몬": 5000,
    "크랜베리": 5000,
    # 두부·가공식품
    "두부": 1500,   "순두부": 1200, "곤약": 1500,   "실곤약": 1000,
    "어묵": 1500,   "맛살": 1200,   "김치": 1500,   "콩비지": 800,
    "두유": 600,
    # 조미료 (액체·분말)
    "간장": 800,    "식초": 600,    "참기름": 3000, "들기름": 4000,
    "식용유": 600,  "올리브유": 4000, "올리브오일": 4000,
    "발사믹식초": 5000, "발사믹소스": 5000, "발사믹크레마": 8000,
    "매실액": 2000, "레몬즙": 5000, "꿀": 3000,     "고춧가루": 4000,
    "된장": 1500,   "고추장": 1500, "머스터드": 2500,
    "드레싱 올리브오일": 5000,
    # 달걀·유제품
    "달걀": 1000,   "계란": 1000,   "우유": 500,    "생크림": 2500,
    "치즈": 5000,   "버터": 5000,   "플레인요거트": 2000,
    # 육류
    "돼지고기": 4000, "소고기": 7000, "닭고기": 2500, "닭가슴살": 2500,
    "베이컨": 5000, "소시지": 2000, "스팸": 4000,   "햄": 3000,
    # 해산물
    "새우": 4000,   "오징어": 3000, "멸치": 3000,   "황태": 5000,
    "북어채": 5000, "꽁치": 3000,   "삼치": 4000,
    "꼬막": 2500,   "골뱅이": 3000, "달래": 2000,   "바지락": 2000,
    "전복": 8000,   "굴": 3000,     "홍합": 2000,   "낙지": 4000,
    "주꾸미": 4000, "문어": 5000,   "게": 5000,     "랍스터": 10000,
    # 육수류
    "사골육수": 600,  "멸치육수": 400,  "다시마육수": 300,
    "채소육수": 400,  "닭육수": 500,    "한우육수": 800,
    "육수": 500,
    # 채소 추가
    "단호박": 1500,  "호박": 1200,   "팽이버섯": 500,
    "대추": 3000,    "건대추": 3000,
    # 음료
    "맥주": 500,     "소주": 300,    "막걸리": 400,   "와인": 3000,
    "화이트와인": 3000, "레드와인": 3000,
    # 채소 추가
    "어린잎채소": 1200, "베이비채소": 1200,
    # 기름 추가
    "튀김기름": 400,
    # 떡류
    "증편": 2000,    "가래떡": 1000,  "절편": 1500,
    # 소스류
    "칠리소스": 1000, "토마토소스": 800, "크림소스": 1500,
    # 기타
    "망고": 3500,    "견과류": 4000,  "빵가루": 500,
    "후르츠칵테일": 600, "과일통조림": 600, "복숭아통조림": 600,
    "알룰로스": 1000, "에리스리톨": 1000, "자일리톨": 1500,
    "치즈": 3500,    "슈레드치즈": 3500,
    # 해산물 추가
    "백합": 3000,    "모시조개": 2500,   "재첩": 3000,
    # 채소 추가
    "토란": 1000,    "우엉": 1000,       "연근": 1500,
    # 해조류
    "미역줄기": 600, "미역": 1000,       "다시마": 2000,
    # 기타
    "발효원종": 1500, "통삼겹": 3500,    "묵은지": 700,
    "뽕잎가루": 3000, "모차렐라치즈": 3000, "슈레드 모차렐라치즈": 3000,
    "블랙올리브": 1500, "그린올리브": 1500,
    "해조국수": 3000, "곤약면": 1000,
    "밥": 200,
    # 소고기 부위
    "안심": 9000,    "등심": 8000,   "채끝": 8000,   "갈비": 7000,
    "양지": 5000,    "사태": 5000,   "불고기": 5000,
    # 돼지고기 부위
    "족발": 3000,    "보쌈": 2500,   "수육": 2500,
    # 과일 상한 조정
    "블루베리": 5000, "아보카도": 4000, "바나나": 1000,
    # 조미료
    "올리고당": 500,  "아가베시럽": 1000, "메이플시럽": 2000,
    # 허브류
    "애플민트": 2000, "바질": 2000,   "로즈메리": 2000, "타임": 2000,
    "파슬리": 1500,  "딜": 2000,     "처빌": 2000,
    # 기타
    "쌀": 500,       "즉석밥": 2000, "박력분": 400,   "강력분": 400,
    "중력분": 400,
    # 해산물 추가
    "대하": 3000,    "아보카도": 3000,
    # 콩류
    "검은콩": 1500,  "불린 검은콩": 1500, "콩": 1000,
    # 육류 추가
    "삼겹살": 3500,  "목살": 3000,   "항정살": 4000,
    # 곡류·면
    "쌀": 500,      "밀가루": 400,  "소면": 800,    "당면": 1000,
    "떡": 1500,
    # 견과
    "잣": 10000,    "호두": 8000,   "아몬드": 6000, "땅콩": 2500,
    "참깨": 3000,   "깨": 3000,
}

# 개 단위 → g 환산
# [FIX] 기존 18개 → 확장. 목록에 없는 재료는 "개당 몇 g인지" 알 수 없어
# 개수 표기 상품(예: "감자 3개")의 단가를 잘못 계산하는 원인이 됐었음.
PIECE_GRAMS: Dict[str, float] = {
    "오렌지": 200, "당근": 200, "양파": 180, "감자": 180,
    "사과": 250,   "토마토": 150, "방울토마토": 12,
    "달걀": 50,    "계란": 50,  "마늘": 5,   "대파": 30,
    "두부": 300,   "순두부": 350, "청양고추": 10, "고추": 10,
    "양배추": 300, "애호박": 250, "오이": 150, "무": 1000,
    "고구마": 150, "배": 400,   "귤": 80,    "레몬": 100,
    "단호박": 1500, "가지": 150, "피망": 120, "파프리카": 180,
    "브로콜리": 400, "새송이버섯": 50, "표고버섯": 20,
    "양상추": 500, "깻잎": 2,   "생강": 10,  "대구": 800,
}

# 무료 재료 (0원)
FREE_SET = {
    "물", "생수", "탄산수", "얼음", "따뜻한물", "미지근한물",
    "다시물", "쌀뜨물", "찬물", "끓인물", "물미지근한것",
    "소금", "후추", "후춧가루", "통후추", "흰후추",
    "저염소금", "저나트륨소금",
}
FREE_KW = ["뜨물", "끓는물"]

# 메모리 캐시
_KAMIS_ROWS = {"ts": 0.0, "rows": [], "loaded": False}
_KAMIS_LOCK = asyncio.Lock()
_NAVER_MEM: Dict[str, Dict] = {}
_NAVER_TS:  Dict[str, float] = {}

# 파일 캐시
def _load_json(path: Path) -> Dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_json(path: Path, data: Dict) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

_PRICE_CACHE = _load_json(_PRICE_CACHE_FILE)

def _price_key(raw: str, amount_g: float) -> str:
    return f"{raw}_{round(amount_g, 1)}"


# ─────────────────────────────────────────────────────────────
# 재료명 정규화 (규칙 기반, Gemini 없음)
# ─────────────────────────────────────────────────────────────

# 복합 재료명 → 핵심 재료 룩업 테이블
_NAME_LOOKUP = {
    "쌀뜨물": "쌀뜨물",   "다시물": "다시물",   "따뜻한물": "물",
    "미지근한물": "물",    "끓인물": "물",        "물미지근한것": "물",
    "소금적당량": "소금",  "후춧가루적당량": "후추",
    "날콩가루": "날콩가루", "콩가루": "콩가루",
    "멸치육수": "멸치육수", "사골육수": "사골육수",
}

# 색깔 수식어 (뒤의 단어가 실제 재료)
_COLOR_PREFIX = {"빨강", "노랑", "파랑", "초록", "흰", "검정", "검은",
                 "붉은", "노란", "푸른", "홍", "황", "청", "적", "백"}

# 조리법 수식어 (뒤의 단어가 실제 재료)
_COOK_PREFIX = {"다진", "볶은", "구운", "삶은", "데친", "불린",
                "건", "냉동", "냉장", "생", "갈은", "썬"}

def _normalize(raw: str) -> str:
    """재료명에서 핵심 재료명 추출 (Gemini 없이 규칙 기반)"""
    text = raw.strip()

    # 룩업 테이블 우선
    if text in _NAME_LOOKUP:
        return _NAME_LOOKUP[text]

    # HTML 태그, 괄호 제거
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)

    # "소스소개 xxx" 제거
    text = re.sub(r"소스소개.*", "", text)
    text = re.sub(r"재료소개.*", "", text)

    # 수량·단위 제거
    text = re.sub(r"\d+(?:\.\d+)?\s*(kg|g|mg|ml|l|개|큰술|작은술|컵|줌|조각|장|마리|포기)", " ", text, flags=re.I)

    # "적당량", "약간" 제거
    text = re.sub(r"(적당량|약간|조금|소량)", "", text)

    # 특수문자 → 공백
    text = re.sub(r"[^\w가-힣]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    words = [w for w in text.split() if len(w) >= 2]
    if not words:
        return raw.strip()

    # 불필요 단어 제거
    _remove = {"소스", "시럽", "드레싱", "양념", "페스토", "퓨레",
               "소스소개", "재료소개", "육수", "반죽", "장식", "재료",
               "필수", "준비", "곁들임"}
    _condiment = {"소금", "설탕", "간장", "식초", "고추장", "된장"}

    filtered = [w for w in words if w not in _remove and w not in _condiment]
    if not filtered:
        return words[0]

    # 색깔 수식어 처리
    if len(filtered) >= 2 and filtered[0] in _COLOR_PREFIX:
        return filtered[1]

    # 조리법 수식어 처리 (2단어 유지)
    if len(filtered) >= 2 and filtered[0] in _COOK_PREFIX:
        return " ".join(filtered[:2])

    # 3단어 이상: 첫 단어만
    if len(filtered) >= 3:
        return filtered[0]

    return " ".join(filtered)


def _is_free(keyword: str) -> bool:
    if keyword in FREE_SET:
        return True
    return any(kw in keyword for kw in FREE_KW)


# ─────────────────────────────────────────────────────────────
# 가격 현실성 검증 (규칙 기반)
# ─────────────────────────────────────────────────────────────
def _is_realistic(keyword: str, price_per_100g: float) -> bool:
    """재료별 상한선으로 이상값 차단"""
    if price_per_100g <= 0:
        return False

    # 물/얼음류 → 무조건 False
    if any(kw in keyword for kw in ["물", "얼음", "생수", "탄산수"]):
        return False

    # PRICE_CAP 딕셔너리에서 상한선 확인
    for key, cap in PRICE_CAP.items():
        if key in keyword or keyword in key:
            return price_per_100g <= cap

    # 기본 상한: 15,000원/100g
    return price_per_100g <= 15000


# ─────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────
def _to_float(v) -> float:
    try:
        return float(str(v or "").replace(",", "").strip())
    except Exception:
        return 0.0

def _extract_weight_g(title: str, kw: str = "") -> float:
    """
    상품명에서 실제 중량(g)을 추출.
    [FIX] 기존에는 kg/L/ml/g 표기만 인식했고, "감자 3개", "계란 30구" 같은
    개수 표기 상품은 중량을 못 찾아 0을 반환 → 호출부의 위험한 폴백
    (아래 elif lp <= 5000: per100g = lp) 때문에 "개당 가격 전체를
    100g당 가격"으로 오인해서 단가가 실제보다 훨씬 높게/낮게 잘못
    계산되는 버그가 있었음. PIECE_GRAMS 테이블로 개수 → g 환산을 추가함.
    """
    t = re.sub(r"<[^>]+>", " ", title.lower())
    t = re.sub(r"\s+", " ", t)
    for pat, mul in [
        (r"(\d+(?:\.\d+)?)\s*kg",         1000),
        (r"(\d+(?:\.\d+)?)\s*[lL](?!\w)", 1000),
        (r"(\d+(?:\.\d+)?)\s*ml",         1),
        (r"(\d+(?:\.\d+)?)\s*g(?!\w)",    1),
    ]:
        m = re.search(pat, t)
        if m:
            val = float(m.group(1)) * mul
            if 10 <= val <= 50000:
                return val

    # 개수 표기(개/구/입/알/통/봉) → PIECE_GRAMS 기준으로 g 환산
    piece_g = PIECE_GRAMS.get(kw, 0)
    if piece_g > 0:
        m = re.search(r"(\d+)\s*(개입|개|구|입|알|통|봉)", t)
        if m:
            count = float(m.group(1))
            val = count * piece_g
            if 10 <= val <= 50000:
                return val

    return 0.0

def _unit_to_g(unit: str, kw: str) -> float:
    u = (unit or "").lower()
    for pat, mul in [
        (r"(\d+(?:\.\d+)?)\s*kg", 1000), (r"(\d+(?:\.\d+)?)\s*g", 1),
        (r"(\d+(?:\.\d+)?)\s*ml", 1),    (r"(\d+(?:\.\d+)?)\s*l", 1000),
    ]:
        m = re.search(pat, u)
        if m:
            return float(m.group(1)) * mul
    m = re.search(r"(\d+(?:\.\d+)?)\s*개", u)
    if m:
        return float(m.group(1)) * PIECE_GRAMS.get(kw, 0)
    return 0.0

def _find_rows(obj) -> List[Dict]:
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "item_name" in obj[0]:
            return obj
        r = []
        for x in obj: r.extend(_find_rows(x))
        return r
    if isinstance(obj, dict):
        if "item_name" in obj and "dpr1" in obj: return [obj]
        r = []
        for v in obj.values(): r.extend(_find_rows(v))
        return r
    return []


# ─────────────────────────────────────────────────────────────
# KAMIS API
# ─────────────────────────────────────────────────────────────
async def _load_kamis() -> List[Dict]:
    now = time.time()
    if now - _KAMIS_ROWS["ts"] < 600 and _KAMIS_ROWS["loaded"]:
        return _KAMIS_ROWS["rows"]
    async with _KAMIS_LOCK:
        if not KAMIS_KEY or not KAMIS_ID:
            _KAMIS_ROWS.update({"ts": time.time(), "rows": [], "loaded": True})
            return []

        async def _fetch(client, cat):
            try:
                res = await client.get(KAMIS_URL, params={
                    "action": "dailyPriceByCategoryList",
                    "p_cert_key": KAMIS_KEY, "p_cert_id": KAMIS_ID,
                    "p_returntype": "json", "p_product_cls_code": "01",
                    "p_item_category_code": cat, "p_country_code": "1101",
                    "p_convert_kg_yn": "N",
                })
                return _find_rows(res.json() if res.status_code == 200 else {})
            except Exception:
                return []

        rows = []
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for r in await asyncio.gather(*[_fetch(client, c) for c in CATEGORY_CODES]):
                rows.extend(r)
        _KAMIS_ROWS.update({"ts": time.time(), "rows": rows, "loaded": True})
        print(f"[price_service] KAMIS loaded: {len(rows)}")
        return rows


def _kamis_query(keyword: str, rows: List[Dict], amount_g: float) -> Optional[Tuple]:
    if not rows: return None
    names, nmap = [], {}
    for row in rows:
        item  = str(row.get("item_name", "")).strip()
        kind  = str(row.get("kind_name", "")).strip()
        label = f"{item} {kind}".strip() if kind else item
        if label:
            names.append(label)
            nmap[label] = row

    clean = [re.sub(r"[^\w가-힣]", " ", n).strip() for n in names]

    for i, cn in enumerate(clean):
        if keyword == cn or keyword in cn or cn in keyword:
            row = nmap[names[i]]
            g = _unit_to_g(str(row.get("unit", "")), keyword)
            p = _to_float(row.get("dpr1"))
            if g > 0 and p > 0:
                per100g = p / g * 100
                if _is_realistic(keyword, per100g):
                    return (per100g, per100g / 100 * amount_g, f"KAMIS {names[i]}")

    matches = get_close_matches(keyword, clean, n=1, cutoff=0.55)
    if matches:
        for i, cn in enumerate(clean):
            if cn == matches[0]:
                row = nmap[names[i]]
                g = _unit_to_g(str(row.get("unit", "")), keyword)
                p = _to_float(row.get("dpr1"))
                if g > 0 and p > 0:
                    per100g = p / g * 100
                    if _is_realistic(keyword, per100g):
                        print(f"[price_service] KAMIS 퍼지: '{keyword}' → '{matches[0]}'")
                        return (per100g, per100g / 100 * amount_g, f"KAMIS {names[i]}")
    return None


# ─────────────────────────────────────────────────────────────
# 네이버 쇼핑 API
# ─────────────────────────────────────────────────────────────
async def _naver_query(keyword: str, amount_g: float) -> Optional[Tuple]:
    if not NAVER_ID or not NAVER_SECRET:
        return None

    now = time.time()
    if keyword in _NAVER_MEM and now - _NAVER_TS.get(keyword, 0) < 600:
        c = _NAVER_MEM[keyword]
        if c:
            return (c["per100g"], c["per100g"] / 100 * amount_g, c["title"])
        return None

    print(f"[price_service] 네이버 검색: '{keyword}'")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                NAVER_URL,
                headers={"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET},
                params={"query": f"{keyword} 100g", "display": 5, "sort": "sim"},
            )
            items = res.json().get("items", []) if res.status_code == 200 else []

        skip = ["세트", "묶음", "박스", "선물", "gift", "set", "기획", "생수",
                "워터", "착즙기", "기계", "용품", "도구", "냄비", "그릇"]
        per100g_list, titles = [], []

        for item in items:
            raw_title = re.sub(r"<[^>]+>", " ", item.get("title", ""))
            title     = re.sub(r"\s+", " ", raw_title).strip()
            lp        = _to_float(item.get("lprice", 0))
            if any(k in title.lower() for k in skip) or lp <= 0:
                continue
            w = _extract_weight_g(title, keyword)
            if w > 0:
                per100g = lp / w * 100
            elif lp <= 5000:
                # [주의] 중량/개수 정보를 상품명에서 전혀 못 찾은 경우의 최후 폴백.
                # 가격이 낮으면 소량 조미료류일 가능성이 높다고 가정하고
                # 상품 가격 자체를 100g당 가격으로 간주함 — 부정확할 수 있으므로
                # PIECE_GRAMS/중량 표기 매칭이 가능한 재료는 위 분기에서 먼저 처리되도록
                # PIECE_GRAMS 테이블을 계속 채워나가는 것이 근본적인 해결책.
                per100g = lp
            else:
                continue

            # 상한선 체크 (네이버 단계에서 바로 필터링)
            if _is_realistic(keyword, per100g):
                per100g_list.append(per100g)
                titles.append(title)

        if not per100g_list:
            # 통과된 결과 없음 → 캐시에 None 저장 (재검색 방지)
            _NAVER_MEM[keyword] = None
            _NAVER_TS[keyword]  = now
            return None

        p100  = median(per100g_list)
        title = titles[0] if titles else ""
        _NAVER_MEM[keyword] = {"per100g": p100, "title": title}
        _NAVER_TS[keyword]  = now
        print(f"[price_service] 네이버 성공: '{keyword}' → {round(p100,1)}원/100g")
        return (p100, p100 / 100 * amount_g, title)

    except Exception as e:
        print(f"[price_service] 네이버 오류 '{keyword}': {e}")
        return None


def _std_avg(keyword: str, amount_g: float) -> Optional[Dict]:
    for key, p in STANDARD_AVERAGE_DB.items():
        if key in keyword or keyword in key:
            return {
                "matched_name":   keyword,
                "unit":           "100g",
                "unit_price_krw": round(p / 100, 4),
                "price_krw":      round(p / 100 * amount_g, 1),
                "source":         "STANDARD_AVERAGE",
            }
    return None

def _save_price(key: str, result: Dict) -> None:
    _PRICE_CACHE[key] = {**result, "updated_at": time.time()}
    _save_json(_PRICE_CACHE_FILE, _PRICE_CACHE)


# ─────────────────────────────────────────────────────────────
# 메인 파이프라인
# ─────────────────────────────────────────────────────────────
async def get_price_for_ingredient(standard_nm: str, amount_g: float) -> Dict:
    """
    규칙 기반 가격 계산 파이프라인 (Gemini 없음)
      1) 가격 캐시 히트 → 즉시 반환
      2) 재료명 정규화 (규칙 기반)
      3) 무료 재료 → 0원
      4) KAMIS → 상한선 체크 후 반환
      5) 네이버 → 상한선 체크 후 반환 or STANDARD_AVERAGE
      6) STANDARD_AVERAGE 최후 수단
    """
    EMPTY = {"matched_name": "", "unit": "", "unit_price_krw": 0.0,
             "price_krw": 0.0, "source": ""}

    if not standard_nm or amount_g <= 0:
        return EMPTY

    # ② 재료명 정규화 (캐시 키 생성 전에 먼저 정규화)
    keyword = _normalize(standard_nm)
    if not keyword:
        return EMPTY

    # ① 캐시 히트 (정규화된 keyword 기준으로 조회)
    cache_key = _price_key(keyword, amount_g)
    if cache_key in _PRICE_CACHE:
        c = _PRICE_CACHE[cache_key]
        return {k: c[k] for k in ("matched_name","unit","unit_price_krw","price_krw","source")}

    # ③ 무료 재료
    if _is_free(keyword):
        result = {"matched_name": keyword, "unit": "",
                  "unit_price_krw": 0.0, "price_krw": 0.0, "source": "zero_cost"}
        _save_price(cache_key, result)
        return result

    # ④ KAMIS
    rows      = await _load_kamis()
    kamis_res = _kamis_query(keyword, rows, amount_g)
    if kamis_res:
        per100g, price_krw, title = kamis_res
        result = {
            "matched_name":   keyword,
            "unit":           "100g",
            "unit_price_krw": round(per100g / 100, 4),
            "price_krw":      round(price_krw, 1),
            "source":         "kamis",
        }
        _save_price(cache_key, result)
        return result

    # ⑤ 네이버 쇼핑 (상한선 체크 내장)
    naver_res = await _naver_query(keyword, amount_g)
    if naver_res:
        per100g, price_krw, title = naver_res
        result = {
            "matched_name":   keyword,
            "unit":           "100g",
            "unit_price_krw": round(per100g / 100, 4),
            "price_krw":      round(price_krw, 1),
            "source":         "naver_shopping",
        }
        _save_price(cache_key, result)
        return result

    # ⑥ STANDARD_AVERAGE
    std = _std_avg(keyword, amount_g)
    result = std or EMPTY
    if result != EMPTY:
        _save_price(cache_key, result)
    return result