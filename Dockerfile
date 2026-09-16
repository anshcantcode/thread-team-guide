FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --requirement requirements.lock && useradd --create-home --uid 10001 thread
COPY thread_agent ./thread_agent
COPY evaluation ./evaluation
COPY scripts/check_theme5.py scripts/check_acceptance.py scripts/check_responsiveness.py ./scripts/
COPY tests ./tests
COPY web ./web
RUN mkdir reports && chown thread:thread reports
USER thread
ENTRYPOINT ["python", "-m", "thread_agent.stdio"]
