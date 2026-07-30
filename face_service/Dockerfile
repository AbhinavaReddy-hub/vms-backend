FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# libgl1 + libglib2.0-0 are opencv's runtime shared libraries. `import cv2`
# fails outright without them.
#
# build-essential is deliberately NOT installed. insightface 1.0.1 ships as a
# pure-Python wheel (Tag: py3-none-any, Root-Is-Purelib: true - no .so/.pyx in
# the package at all) and every other dependency here has a manylinux wheel, so
# nothing compiles from source. Leaving the toolchain out saves roughly 400MB in
# the final image and several minutes of build time, and it is what makes this
# service buildable on a 1GB t3.micro at all - the old insightface 0.7.3 built
# from source and would get OOM-killed there.
# If a future insightface release goes back to source-only, add build-essential
# back to this line.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source, so a code edit doesn't reinstall onnxruntime.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Model weights (~280MB) download on first start. insightface 1.0.1 hardcodes
# the cache location as root='~/.insightface' in FaceAnalysis.__init__ and
# resolves it with os.path.expanduser - there is NO INSIGHTFACE_HOME env var in
# this version, so setting $HOME is the only way to move it. It has to move,
# because the default expands to /root/.insightface which a non-root user
# cannot write. docker-compose mounts a named volume at the path below so the
# download happens once and survives rebuilds.
ENV HOME=/home/faceuser
RUN useradd --create-home --uid 10001 faceuser \
    && mkdir -p /home/faceuser/.insightface \
    && chown -R faceuser:faceuser /app /home/faceuser
USER faceuser

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
