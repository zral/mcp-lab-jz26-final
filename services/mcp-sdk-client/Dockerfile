FROM python:3.14-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy test client
COPY test_mcp_sdk.py .

# Set environment variable for MCP server URL (configurable)
ENV MCP_SERVER_URL=http://mcp-server:8000

# Run the compliance test
CMD ["python", "test_mcp_sdk.py"]
