"""
config.py
환경변수(.env)를 읽어 전역 설정 객체를 제공합니다.
모든 API 키는 이 파일을 통해서만 접근합니다 — 프론트엔드에 절대 노출되지 않습니다.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

class Settings(BaseSettings):
    # ── 식약처 레시피 DB ──────────────────────────────────────
    mfds_api_key: str = "MOCK"
    mfds_base_url: str = (
        "http://openapi.foodsafetykorea.go.kr/api"
    )

    # ── 농촌진흥청 영양성분 DB ────────────────────────────────
    rda_api_key: str = "MOCK"
    rda_base_url: str = (
        "https://api.nal.usda.gov/fdc/v1"  # TODO: 실제 농진청 엔드포인트로 교체
        # 실제: "https://apis.data.go.kr/1471000/FoodNtrIrdntInfoService1"
    )

    # ── KAMIS 가격 API ────────────────────────────────────────
    kamis_api_key: str = "MOCK"
    kamis_api_id: str = "MOCK"
    kamis_base_url: str = "https://www.kamis.or.kr/service/price/xml.do"

    # ── Gemini AI API (1차) ────────────────────────────────────
    # [FIX] 실제 키를 코드 기본값으로 박아두면 Git에 그대로 노출됨.
    # 반드시 .env 파일에서만 채우고, 여기 기본값은 빈 문자열로 둔다.
    gemini_api_key: str = ""

    # ── Groq AI API (Gemini 429/타임아웃 시 폴백) ───────────────
    groq_api_key: str = ""
    groq_model:   str = "openai/gpt-oss-120b"

    # ── 앱 설정 ───────────────────────────────────────────────
    # [FIX] use_mock은 코드 어디에서도 쓰이지 않는다. 샘플 JSON 모드는
    # 이미 제거됐고 각 서비스가 실제 API만 호출한다. 혼란을 막기 위해 삭제.
    port: int = 8888               # main.py 직접 실행 시 사용 (.env의 PORT가 우선)
    allowed_origins: str = "*"

    class Config:
        # [FIX] 상대경로(".env")로 두면 "터미널이 어느 폴더에 있는지"에 따라
        # .env를 못 찾는 문제가 있었음(backend 폴더에서 실행하면 backend/.env를
        # 찾으려 하는데, 실제 .env는 backend보다 한 단계 위에 있음).
        # config.py 파일 위치를 기준으로 한 절대경로로 고정.
        env_file = str(Path(__file__).resolve().parent.parent / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"  # .env에 Settings에 정의 안 된 항목(NAVER_* 등)이 있어도 무시하고 통과


@lru_cache()
def get_settings() -> Settings:
    """설정 싱글톤 반환 (최초 1회만 파일 읽음)"""
    return Settings()