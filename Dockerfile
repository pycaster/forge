FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY gateway/ gateway/
COPY sdk/ sdk/
USER 10001:10001

FROM runtime AS echo
COPY examples/echo/ examples/echo/
CMD ["python", "-m", "examples.echo.worker"]

# Keep Gateway last so a plain docker build creates the platform image.
FROM runtime AS gateway
CMD ["python", "-m", "gateway"]
