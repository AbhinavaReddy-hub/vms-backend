"""Face detection and embedding. No web framework code in this file on
purpose - it can be tested on its own, and swapped without touching the API.

Model: InsightFace 'buffalo_s'
  - Detector: SCRFD-500MF (lightweight - fast on CPU)
  - Embedding: MobileFaceNet ArcFace (512-number fingerprint per face)

Deliberately swapped from 'buffalo_l' (ResNet50 recognition backbone,
noticeably more accurate but slower) for speed on CPU-only hardware. Only a
good trade at small registered-visitor counts (discussed and accepted at
~10 users) - buffalo_l's accuracy edge matters far more once there are
enough registered faces for two people to plausibly get confused. Embeddings
are NOT compatible across the two packs (different backbone = different
vector space) - every visitor needs to re-register their face after this
switch; see the one-time cleanup this required in visitor_face_data.
"""
import time

import numpy as np
from insightface.app import FaceAnalysis


class FaceEngine:
    def __init__(self):
        # buffalo_s ships 5 models (detection, 2x landmark, genderage,
        # recognition). get_embedding() below only ever reads bbox +
        # normed_embedding, so landmark/genderage are pure wasted inference
        # on every face, every request - allowed_modules skips loading and
        # running them at all.
        #
        # providers is a preference list, not a hard requirement: onnxruntime
        # silently falls back to the next entry if CUDAExecutionProvider
        # isn't available (no GPU / no onnxruntime-gpu installed), so this is
        # safe on CPU-only machines too. To actually get GPU acceleration you
        # also need `pip install onnxruntime-gpu` (it replaces plain
        # onnxruntime - the CPU-only wheel has no CUDA kernels to fall into).
        self.app = FaceAnalysis(
            name="buffalo_s",
            allowed_modules=["detection", "recognition"],
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        # det_size lowered from 640x640 to 320x320 - the detector looks at a
        # smaller version of the frame, which is noticeably faster per frame
        # and still finds faces fine at normal kiosk/webcam distance. This is
        # the main lag fix: less pixels to scan = less time per request.
        self.app.prepare(ctx_id=0, det_size=(320, 320))

    def get_embedding(self, image_bgr: np.ndarray):
        """Returns (embedding, bbox, inference_ms) for the largest face, or (None, None, ms)."""
        start = time.perf_counter()
        faces = self.app.get(image_bgr)
        inference_ms = (time.perf_counter() - start) * 1000
        if not faces:
            return None, None, inference_ms
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        face = faces[0]
        bbox = [int(v) for v in face.bbox]  # [x1, y1, x2, y2]
        return face.normed_embedding, bbox, inference_ms

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))
