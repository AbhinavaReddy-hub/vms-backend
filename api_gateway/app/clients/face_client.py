"""The ONLY place that knows the Face Service exists.

If you swap InsightFace for AWS Rekognition or anything else, this file is
the only one that changes. Nothing else in the codebase imports it directly
except through here.

If the Face Service is not running, every call degrades gracefully instead
of crashing - so the rest of the backend stays testable on its own.
"""
import base64
import json
import logging

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class FaceClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0):
        self.base_url = (base_url or settings.FACE_SERVICE_URL).rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def embed(self, image_b64: str) -> dict:
        """Returns {'face_detected': bool, 'embedding': [...], 'bbox': [...], 'inference_ms': float}"""
        try:
            raw = base64.b64decode(_strip_data_url(image_b64))
        except Exception:
            return {"face_detected": False, "error": "Bad base64 image"}

        try:
            r = httpx.post(
                f"{self.base_url}/embed",
                files={"image": ("frame.jpg", raw, "image/jpeg")},
                timeout=self.timeout,
            )
            r.raise_for_status()
            result = r.json()
            log.info("face embed: detected=%s bbox=%s [%sms]",
                     result.get("face_detected"), result.get("bbox"), result.get("inference_ms"))
            return result
        except Exception as e:
            log.warning("Face service unavailable: %s", e)
            return {"face_detected": False, "error": "face_service_unavailable"}

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def match_against(self, embedding: list[float], candidates: list[tuple[int, str]],
                      threshold: float | None = None) -> tuple[int | None, float]:
        """candidates = [(visitor_id, embedding_json), ...]

        Brute force comparison. Instant for the few hundred to few thousand
        visitors an office has. Past ~10k, move this to pgvector or FAISS.
        """
        threshold = threshold if threshold is not None else settings.FACE_MATCH_THRESHOLD
        best_id, best_score = None, -1.0
        for visitor_id, emb_json in candidates:
            try:
                other = json.loads(emb_json)
            except Exception:
                continue
            score = self.cosine_similarity(embedding, other)
            if score > best_score:
                best_score, best_id = score, visitor_id
        if best_score >= threshold:
            return best_id, best_score
        return None, max(best_score, 0.0)


def _strip_data_url(s: str) -> str:
    return s.split(",", 1)[1] if s.startswith("data:") else s


face_client = FaceClient()
