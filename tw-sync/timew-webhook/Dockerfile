FROM python:3.12-slim

RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  timewarrior ca-certificates tzdata bash \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh

RUN mkdir -p /var/lib/timew
ENV HOME=/var/lib/timew

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
