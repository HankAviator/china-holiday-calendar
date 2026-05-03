FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m playwright install chromium
