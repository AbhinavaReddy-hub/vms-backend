FROM python:3.11-slim

# PYTHONUNBUFFERED: without it Python buffers stdout when it isn't a TTY, so
# logging output can lag or vanish from `docker logs` - which is exactly when
# you need it, debugging a container that died during startup.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# requirements.txt is copied and installed on its own, BEFORE the source. Docker
# caches that layer, so editing a route rebuilds in seconds instead of
# reinstalling every dependency. Copying source first would bust the cache on
# every single code change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# This service never writes to disk (no open() for write, no uploads dir, no
# mkdir anywhere in app/ or seed.py), so it can drop root entirely. Postgres
# holds all the state.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# --proxy-headers is REQUIRED here, not optional polish. Behind CloudFront,
# request.client.host is the CDN edge server's IP unless Starlette is told to
# read X-Forwarded-For. Two places depend on the real visitor IP:
#   app/core/deps.py       -> the "ip" recorded in the audit log
#   app/api/v1/public.py   -> the rate-limit key on every public endpoint
# Without this flag the audit trail logs meaningless CDN addresses.
#
# --forwarded-allow-ips=* trusts whatever the upstream proxy claims. That is
# ONLY safe because the security group restricts port 80 to CloudFront's
# origin-facing prefix list. If port 80 is ever opened wider, anyone can forge
# their IP in the audit log - so these two settings must be changed together.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
