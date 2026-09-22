from fastapi import APIRouter, HTTPException, Request

from backend.schemas import FuelData as FuelDataSchema, IngestAcceptedResponse

router = APIRouter()


@router.post("/", response_model=IngestAcceptedResponse, status_code=202)
def ingest_fuel_data(payload: FuelDataSchema, request: Request):
    """
    Accepts a fuel reading and publishes it to Kafka (fuel.readings.raw)
    for the ingestion consumer to actually validate-and-store.

    This endpoint deliberately does NOT write to the database anymore
    (see docs/adr/0001-kafka-ingestion.md, Phase 3). A 202 response means
    "accepted for processing", not "stored" — the write happens moments
    later, asynchronously, in ingestion_consumer/main.py. This mirrors
    exactly what the station simulator's Kafka sink has done since Phase 1;
    /ingest is now just a second producer into the same pipeline, using
    the same message key scheme so HTTP-sourced and simulator-sourced
    readings for the same tank stay correctly ordered on the same
    partition.
    """
    try:
        request.app.state.kafka_producer.send(
            station_id=payload.station_id,
            fuel_type=payload.fuel_type,
            # mode="json" converts non-JSON-native types (here, `timestamp`,
            # a datetime) into JSON-safe values (an ISO 8601 string) before
            # this dict gets handed to json.dumps() inside the producer.
            # payload.dict()/.model_dump() alone would leave it as a Python
            # datetime object, which json.dumps() cannot serialize —
            # this was the cause of the 500 error.
            payload=payload.model_dump(mode="json"),
        )
    except BufferError:
        # The producer's local queue is full, meaning Kafka isn't keeping
        # up (or is unreachable) and hasn't cleared it via delivery
        # callbacks yet. Fail loudly rather than silently pretending this
        # reading was queued when it wasn't.
        raise HTTPException(
            status_code=503,
            detail="Ingestion pipeline is temporarily overloaded, please retry.",
        )

    return IngestAcceptedResponse(
        station_id=payload.station_id,
        fuel_type=payload.fuel_type,
        timestamp=payload.timestamp,
    )