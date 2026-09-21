"""KUDOS RAG API 진입점.

python main.py --active-profile=local
"""
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import global_variable
from src.config.profile import Profile
from src.controller import ask_controller

__fastapi_config = Profile().get_config("fastapi")
__swagger_config = Profile().get_config("swagger")
__common_config = Profile().get_common_config()
__STATIC_DIR = f"{global_variable.PROJECT_RESOURCE_DIR}/static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 기동 시 검색 인덱스 로드. 테스트에서 context 를 미리 주입한 경우 재생성하지 않는다
    if ask_controller.context is None:
        ask_controller.init_context()
    yield


app = FastAPI(
    title=__swagger_config["title"],
    summary=__swagger_config.get("summary", ""),
    version=__common_config["version"],
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=__STATIC_DIR), name="static")
app.include_router(ask_controller.router)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(f"{__STATIC_DIR}/index.html", media_type="text/html")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=__fastapi_config["host"],
        port=int(__fastapi_config["port"]),
        reload=__fastapi_config.get("reload", "False").lower() == "true",
    )
