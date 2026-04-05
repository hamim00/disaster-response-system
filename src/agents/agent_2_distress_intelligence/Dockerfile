FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements_agent2.txt /app/requirements_agent2.txt
RUN pip install --no-cache-dir -r requirements_agent2.txt

# Copy source code
COPY src/agents/agent_2_distress_intelligence /app/agent2

WORKDIR /app/agent2

# Expose port
EXPOSE 8002

# Run agent
CMD ["python", "main.py"]
