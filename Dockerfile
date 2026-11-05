FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 PORT=10000 ATLAS_DATA_DIR=/data
WORKDIR /app
RUN useradd -r -u 10001 -m atlas && mkdir -p /data && chown atlas:atlas /data
COPY --chown=atlas:atlas . .
USER atlas
EXPOSE 10000
HEALTHCHECK --interval=45s --timeout=8s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:10000/api/health',timeout=5)" || exit 1
CMD ["python", "live_server.py"]
