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

app = FastAPI(title="Recipe Analysis System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True)