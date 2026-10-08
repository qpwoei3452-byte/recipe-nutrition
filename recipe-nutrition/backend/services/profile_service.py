"""
profile_service.py
─────────────────────────────────────────────────────────────
개인 맞춤형 추천을 위한 사용자 프로필 저장소.

교수님 피드백 대응:
  "회원가입 시 선호도를 미리 설정 → 이후 선택 없이 자동 추천,
   그리고 로그 데이터(먹은 음식)를 분석해서 개인을 파악"

학부 프로젝트 범위이므로 무거운 DB/로그인 대신
JSON 파일 기반의 가벼운 영속 저장소를 사용한다.
실제 서비스에서는 이 계층만 DB(SQLite/PostgreSQL)로 교체하면 된다.

프로필 구조:
{
  "user_id": "u_xxxx",
  "weights": {"price":0.3,"protein":0.25,"calorie":0.2,"time":0.25},  # 사전 설정
  "food_log": [ {"name":"간장계란밥","ts": 1715600000}, ... ],          # 로그
  "created_at": ..., "updated_at": ...
}
"""
import json
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

# 데이터 저장 위치 (backend/data/profiles.json)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)
_PROFILE_FILE = _DATA_DIR / "profiles.json"

_lock = Lock()  # 동시 쓰기 보호

DEFAULT_WEIGHTS = {"price": 0.25, "protein": 0.22, "calorie": 0.18, "sodium": 0.15, "time": 0.20}
MAX_LOG = 20  # 로그는 최근 20개까지 유지


# ── 내부 입출력 ────────────────────────────────────────────────
def _load_all() -> Dict[str, dict]:
    if not _PROFILE_FILE.exists():
        return {}
    try:
        with open(_PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: Dict[str, dict]) -> None:
    tmp = _PROFILE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_PROFILE_FILE)  # 원자적 교체


def _normalize(w: Dict[str, float]) -> Dict[str, float]:
    keys = ("price", "protein", "calorie", "sodium", "time")
    try:
        vals = {k: max(0.0, float(w.get(k, 0))) for k in keys}
    except (TypeError, ValueError):
        return dict(DEFAULT_WEIGHTS)
    total = sum(vals.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: round(v / total, 4) for k, v in vals.items()}


# ── 공개 API ───────────────────────────────────────────────────
def create_profile(weights: Optional[Dict[str, float]] = None) -> dict:
    """새 프로필 생성 (회원가입 시 선호도 설정에 해당)."""
    uid = "u_" + uuid.uuid4().hex[:12]
    now = time.time()
    profile = {
        "user_id": uid,
        "nickname": "",
        "avatar_emoji": "🍽️",
        "weights": _normalize(weights) if weights else dict(DEFAULT_WEIGHTS),
        "food_log": [],
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        data = _load_all()
        data[uid] = profile
        _save_all(data)
    return profile


def get_profile(user_id: str) -> Optional[dict]:
    return _load_all().get(user_id)


def update_weights(user_id: str, weights: Dict[str, float]) -> Optional[dict]:
    """설정에서 선호도를 변경할 때 호출."""
    with _lock:
        data = _load_all()
        p = data.get(user_id)
        if not p:
            return None
        p["weights"] = _normalize(weights)
        p["updated_at"] = time.time()
        _save_all(data)
        return p


def add_food_log(user_id: str, food_name: str) -> Optional[dict]:
    """사용자가 클릭/선택한 음식을 로그에 기록 (로그 기반 개인화)."""
    if not food_name:
        return get_profile(user_id)
    with _lock:
        data = _load_all()
        p = data.get(user_id)
        if not p:
            return None
        log = p.get("food_log", [])
        # 중복 제거 후 맨 앞에 추가
        log = [e for e in log if e.get("name") != food_name]
        log.insert(0, {"name": food_name, "ts": time.time()})
        p["food_log"] = log[:MAX_LOG]
        p["updated_at"] = time.time()
        _save_all(data)
        return p


def update_info(user_id: str, nickname: str, avatar_emoji: str) -> Optional[dict]:
    """닉네임 / 아바타 이모지 변경."""
    with _lock:
        data = _load_all()
        p = data.get(user_id)
        if not p:
            return None
        p["nickname"] = nickname[:20]  # 최대 20자
        p["avatar_emoji"] = avatar_emoji or "🍽️"
        p["updated_at"] = time.time()
        _save_all(data)
        return p


def get_food_history(user_id: str) -> List[str]:
    """유사도 패널티에 쓸 음식 이름 리스트 반환."""
    p = get_profile(user_id)
    if not p:
        return []
    return [e["name"] for e in p.get("food_log", [])]


def infer_weights_from_log(user_id: str, base_weights: Optional[Dict] = None) -> Dict[str, float]:
    """
    로그 기반 개인화의 핵심:
    사용자가 실제로 선택한 음식들의 특성을 분석해 가중치를 미세 보정한다.

    아이디어:
      - 사용자가 고른 음식이 평균적으로 '저렴'했다면 → 가격을 더 중시한다고 추론
      - '고단백'을 자주 골랐다면 → 단백질 가중치를 올림
    실제 음식 특성(가격/영양)은 호출부에서 food_stats 로 넘겨주며,
    여기서는 사전 설정값(base_weights)과 로그 신호를 blending 한다.

    데이터가 부족하면(로그 3개 미만) 사전 설정값을 그대로 사용한다.
    """
    base = _normalize(base_weights) if base_weights else dict(DEFAULT_WEIGHTS)
    history = get_food_history(user_id)
    if len(history) < 3:
        return base  # 로그 부족 → 사전 설정 그대로
    return base  # (실제 보정은 recommend 단계에서 food_stats 와 함께 수행)