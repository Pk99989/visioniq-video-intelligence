FROM python:3.12-slim
# Phase 10: unbuffered stdout so JSON log lines flush immediately
# when the container's stdout is redirected to a file or a log driver.
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 5 --timeout 120 -r requirements.txt
COPY . .
RUN chmod +x entrypoint.sh
# Phase 12: run as a non-root user. The image creates the `visioniq`
# user and owns /app to it; the entrypoint runs as root (the image's
# default user) so it can fix the storage volume's ownership — named
# volumes created by the pre-0.14 root images are root-owned — and
# then drops to `visioniq` before starting the server/worker.
RUN useradd -m -u 10001 visioniq && chown -R visioniq:visioniq /app
EXPOSE 8000
# Phase 12: the container is healthy when the API answers /health.
# python, not curl — the slim image has no curl.
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"
ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
