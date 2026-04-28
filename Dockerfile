FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for pymssql
RUN apt-get update && apt-get install -y \
    freetds-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Azure Container Apps default port
EXPOSE 8080

# Run the MCP server over HTTP/SSE
CMD ["python", "-m", "mssql_mcp_server"]
