FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY server.py .

RUN useradd --system --no-create-home mcp
USER mcp
EXPOSE 8001
CMD ["python", "server.py"]
