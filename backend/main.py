from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.database.database import engine
from backend.routes import data, ingest, prophet_routes, report_routes
from backend.database import models
from backend.agent.watcher import start_watcher_async
from kafka_common.readings_producer import ReadingsProducer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background agent that polls for new critical alerts
    # and decides/executes an automated response (reorder / notify / escalate).
    await start_watcher_async()

    # One shared Kafka producer for the lifetime of the app, used by
    # POST /ingest to publish readings instead of writing to the DB
    # directly (see docs/adr/0001-kafka-ingestion.md, Phase 3). Created
    # once here rather than per-request, for the same reason the station
    # simulator shares a single producer across its threads: producer
    # clients are meant to be long-lived and reused, not recreated
    # constantly.
    app.state.kafka_producer = ReadingsProducer()

    yield

    # Flush any in-flight messages before the process actually exits, so
    # a shutdown doesn't silently drop the last few accepted readings.
    app.state.kafka_producer.close()


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