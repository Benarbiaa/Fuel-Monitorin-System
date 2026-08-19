from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.database.database import engine
from backend.routes import data, ingest, prophet_routes, report_routes
from backend.database import models
from backend.agent.watcher import start_watcher_async


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background agent that polls for new critical alerts
    # and decides/executes an automated response (reorder / notify / escalate).
    await start_watcher_async()
    yield


app = FastAPI(
    title="Fuel Monitor API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
models.Base.metadata.create_all(bind=engine)
app.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
app.include_router(data.router, tags=["Read"])
app.include_router(report_routes.router, tags=["Report"]) 
app.include_router(prophet_routes.router)