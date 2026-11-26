# 네이버 가격비교 상품 목록 추출기의 시험용 이미지.
#
#   docker build -t naver-pydoll .
#   docker run --rm -v "$PWD/docker-data:/data" naver-pydoll "LG 그램 16인치 5060"
#
# /data 볼륨에 Chrome 프로필(/data/profile), 결과(/data/products.json),
# 보안 확인 전달 폴더(/data/relay)가 남는다. 컨테이너 하나에 프로필 하나, 고정 IP 하나를 쓴다.
FROM python:3.12-slim-bookworm

ARG TARGETARCH

# 브라우저: x86 서버에서는 정식 Google Chrome, ARM(Apple Silicon 등)에서는 Chromium.
# (Google Chrome 은 Linux ARM 용이 없다.)
# 폰트: fingerprints.py 의 LINUX_FONTS 와 정확히 맞춘다. 한글 폰트가 없으면 글자가 깨진다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tzdata \
      fonts-dejavu-core fonts-liberation fonts-noto-cjk \
 && if [ "$TARGETARCH" = "amd64" ]; then \
      curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
   && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
   && apt-get update \
   && apt-get install -y --no-install-recommends google-chrome-stable \
   && ln -s /usr/bin/google-chrome-stable /usr/local/bin/browser; \
    else \
      apt-get install -y --no-install-recommends chromium \
   && ln -s /usr/bin/chromium /usr/local/bin/browser; \
    fi \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Seoul \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    CHROME_BINARY=/usr/local/bin/browser \
    CHROME_NO_SANDBOX=1 \
    RELAY_DIR=/data/relay \
    RELAY_LOCK_DIR=/data/relay

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY stealth_visit.py fingerprints.py naver_products.py human_relay.py ./

# root 가 아닌 사용자로 실행한다.
RUN useradd --create-home app && mkdir -p /data && chown app:app /data
USER app
VOLUME /data

# 컨테이너에는 화면이 없으므로 항상 헤드리스. 보안 확인은 --relay 로 사람에게 전달한다
# (기본 file: /data/relay 폴더. 운영에서는 `--relay telegram` 또는 `--relay slack`).
ENTRYPOINT ["python", "naver_products.py", "--headless", \
            "--user-data-dir", "/data/profile", "-o", "/data/products.json"]
CMD ["LG 그램 16인치 5060", "--relay", "file"]
