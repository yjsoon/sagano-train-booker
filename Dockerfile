FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py .
COPY .env.example .

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "monitor.py"]
CMD ["--dates", "2025-12-02"]
