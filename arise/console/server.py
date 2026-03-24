from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .registry import AgentRegistry
from .routes import agents


def create_console_app(data_dir: str = "~/.arise/console") -> FastAPI:
    app = FastAPI(title="ARISE Console", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    registry = AgentRegistry(data_dir=data_dir)
    agents.init(registry)
    app.include_router(agents.router)

    return app
