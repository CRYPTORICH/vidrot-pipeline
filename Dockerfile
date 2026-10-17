FROM python:3.12-slim-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /usr/sbin/nologin vidrot

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod 755 /app/docker-entrypoint.sh \
  && mkdir -p /data \
  && chown -R vidrot:vidrot /app /data

ENV VIDROT_DATA=/data \
    VIDROT_HOST=0.0.0.0 \
    VIDROT_PORT=8080 \
    PORT=8080 \
    VIDROT_SECURE=1 \
    VIDROT_TRUST_PROXY=1 \
    VIDROT_NO_BROWSER=1 \
    PYTHONUNBUFFERED=1

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz')"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
