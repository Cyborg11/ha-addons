ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip \
    && pip install --no-cache-dir --break-system-packages \
        "fastapi>=0.110" "uvicorn[standard]>=0.29" "websockets>=12" "httpx>=0.27" "segno>=1.6"

COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app
CMD ["/run.sh"]
