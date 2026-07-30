"""Face Recognition microservice.

This service knows NOTHING about visitors, invites, hosts, or the database.
Image in, numbers out. That is the whole contract.

It has no public port in docker-compose - only the API Gateway can reach it
over the internal network. It is not password protected; it is unreachable,
which is stronger.
"""
import logging

import numpy as np
import cv2
from fastapi import FastAPI, File, UploadFile

from app.face_engine import FaceEngine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Face Recognition Service", version="1.0.0")

print("Loading face model... (first run downloads weights, ~280MB)")
engine = FaceEngine()
print("Face service ready.")


def _read(file_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


@app.post("/embed")
async def embed(image: UploadFile = File(...)):
    img = _read(await image.read())
    if img is None:
        return {"face_detected": False, "error": "Could not read image"}
    embedding, bbox, inference_ms = engine.get_embedding(img)
    if embedding is None:
        log.info("embed: no face detected [%.1fms]", inference_ms)
        return {"face_detected": False, "inference_ms": round(inference_ms, 1)}
    log.info("embed: face detected bbox=%s [%.1fms]", bbox, inference_ms)
    return {"face_detected": True, "embedding": embedding.tolist(), "bbox": bbox,
            "inference_ms": round(inference_ms, 1)}


@app.post("/compare")
async def compare(image_a: UploadFile = File(...), image_b: UploadFile = File(...)):
    ea, _, _ = engine.get_embedding(_read(await image_a.read()))
    eb, _, _ = engine.get_embedding(_read(await image_b.read()))
    if ea is None or eb is None:
        return {"success": False, "message": "Face not found in one of the images"}
    return {"success": True, "score": round(engine.cosine_similarity(ea, eb), 4)}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "face_service", "model": "buffalo_s"}
