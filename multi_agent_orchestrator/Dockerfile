FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt* ./
RUN pip install --no-cache-dir langgraph langchain-anthropic psycopg2-binary python-dotenv

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "orchestrator.py"]
