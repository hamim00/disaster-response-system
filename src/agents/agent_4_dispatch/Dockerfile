FROM python:3.12-slim

WORKDIR /app

# Copy shared modules first
COPY shared/ /app/shared/

# Copy agent code
COPY src/agents/agent_4_dispatch/ /app/src/agents/agent_4_dispatch/
COPY src/__init__.py /app/src/__init__.py
COPY src/agents/__init__.py /app/src/agents/__init__.py

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi>=0.109.0 \
    uvicorn>=0.27.0 \
    asyncpg>=0.29.0 \
    redis>=5.0.0 \
    pydantic>=2.5.0 \
    python-dotenv>=1.0.0 \
    python-multipart>=0.0.6

EXPOSE 8004

CMD ["python", "-m", "src.agents.agent_4_dispatch.main"]