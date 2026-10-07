from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from routers import recipe
from routers import profile
from routers import user   # ← 추가

try:
    from routers import export
except Exception as e:
    export = None
    print(f"[main] export router import skipped: {e}")

import os

from config import get_settings

_settings = get_settings()

app = FastAPI(title="Recipe Analysis System")

# [FIX] 예전에는 CORS 허용 출처가 ["*"]로 하드코딩돼 있어 config.allowed_origins
# 설정이 죽어 있었다. .env의 ALLOWED_ORIGINS를 실제로 반영한다.
#   ALLOWED_ORIGINS=*                         → 전체 허용 (개발용 기본값)
#   ALLOWED_ORIGINS=https://a.com,https://b.com → 지정한 출처만 허용
_origins = [o.strip() for o in (_settings.allowed_origins or "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
print(f"[main] CORS 허용 출처: {_origins}")


@app.middleware("http")
async def disable_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(recipe.router)
app.include_router(profile.router)
app.include_router(user.router)   # ← 추가

if export is not None:
    try:
        app.include_router(export.router)
    except Exception as e:
        print(f"[main] export router include skipped: {e}")


@app.get("/api/health")
async def health():
    return JSONResponse({"ok": True})


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(
            str(FRONTEND_DIR / "index.html"),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
else:
    print(f"[main] frontend directory not found: {FRONTEND_DIR}")


if __name__ == "__main__":
    import uvicorn
    # [FIX] 포트가 8888로 하드코딩돼 있어 .env의 PORT 설정이 무시됐고,
    # 로컬(8888)과 배포(railway.toml의 $PORT) 동작이 달라 혼란의 원인이었다.
    _port = int(os.getenv("PORT") or _settings.port or 8888)
    print(f"[main] http://localhost:{_port} 에서 실행합니다")
    uvicorn.run("main:app", host="0.0.0.0", port=_port, reload=True)