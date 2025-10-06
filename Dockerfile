FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends tzdata ca-certificates ffmpeg     && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install -U pip && pip install -r /app/requirements.txt

COPY . /app
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/bin/bash", "-lc", "bash /app/entrypoint.sh"]