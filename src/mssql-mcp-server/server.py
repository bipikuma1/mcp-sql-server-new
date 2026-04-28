import asyncio
import logging
import os
import re
import secrets
import pymssql
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Resource, Tool, TextContent
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mssql_mcp_server")

def validate_table_name(table_name: str) -> str:
    """Validate and escape table name to prevent SQL injection."""
    # Allow only alphanumeric, underscore, and dot (for schema.table)
    if not re.match(r'^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)?$', table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    
    # Split schema and table if present
    parts = table_name.split('.')
    if len(parts) == 2:
        # Escape both schema and table name
        return f"[{parts[0]}].[{parts[1]}]"
    else:
        # Just table name
        return f"[{table_name}]"

def _parse_connection_string(conn_str: str) -> dict:
    """
    Parse an ADO.NET / JDBC-style Azure SQL connection string into pymssql kwargs.
    Expected format (any order, semicolon-separated):
      Server=tcp:<host>,<port>;Initial Catalog=<db>;
      User ID=<user>;Password=<pass>;Encrypt=yes;...
    """
    params = {}
    for part in conn_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        params[key.strip().lower()] = value.strip()

    # Resolve server + port
    raw_server = (
        params.get("server")
        or params.get("data source")
        or params.get("address")
        or "localhost"
    )
    # Strip leading "tcp:" that Azure portal adds
    raw_server = re.sub(r"^tcp:", "", raw_server, flags=re.IGNORECASE)
    if "," in raw_server:
        host, port_str = raw_server.rsplit(",", 1)
        port = int(port_str.strip())
    else:
        host = raw_server
        port = 1433

    database = (
        params.get("initial catalog")
        or params.get("database")
    )
    user = params.get("user id") or params.get("uid")
    password = params.get("password") or params.get("pwd")

    if not all([host, database, user, password]):
        raise ValueError(
            "Connection string must include Server, Initial Catalog, User ID, and Password"
        )

    config = {
        "server": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "tds_version": "7.4",  # Required for Azure SQL
    }
    logger.info(f"Parsed connection string — server: {host}:{port}, database: {database}, user: {user}")
    return config


def get_db_config():
    """
    Get database configuration.
    Priority:
      1. MSSQL_CONNECTION_STRING  (Azure SQL connection string — recommended for ACA)
      2. Individual MSSQL_* env vars (legacy / local dev)
    """
    conn_str = os.getenv("MSSQL_CONNECTION_STRING")
    if conn_str:
        logger.info("Using MSSQL_CONNECTION_STRING")
        return _parse_connection_string(conn_str)

    # --- Legacy individual env vars (kept for local/dev use) ---
    server = os.getenv("MSSQL_SERVER", "localhost")
    logger.info(f"Using MSSQL_SERVER: {server}")

    if server.startswith("(localdb)\\"):
        instance_name = server.replace("(localdb)\\", "")
        server = f".\\{instance_name}"
        logger.info(f"Detected LocalDB, converted to: {server}")

    config = {
        "server": server,
        "user": os.getenv("MSSQL_USER"),
        "password": os.getenv("MSSQL_PASSWORD"),
        "database": os.getenv("MSSQL_DATABASE"),
        "port": 1433,
    }

    port = os.getenv("MSSQL_PORT")
    if port:
        try:
            config["port"] = int(port)
        except ValueError:
            logger.warning(f"Invalid MSSQL_PORT value: {port}. Using 1433.")

    if config["server"] and ".database.windows.net" in config["server"]:
        config["tds_version"] = "7.4"
        if os.getenv("MSSQL_ENCRYPT", "true").lower() == "true":
            config["server"] += ";Encrypt=yes;TrustServerCertificate=no"
    else:
        encrypt_str = os.getenv("MSSQL_ENCRYPT", "false")
        if encrypt_str.lower() == "true":
            config["tds_version"] = "7.4"
            config["server"] += ";Encrypt=yes;TrustServerCertificate=yes"

    use_windows_auth = os.getenv("MSSQL_WINDOWS_AUTH", "false").lower() == "true"
    if use_windows_auth:
        if not config["database"]:
            raise ValueError("MSSQL_DATABASE is required")
        config.pop("user", None)
        config.pop("password", None)
        logger.info("Using Windows Authentication")
    else:
        if not all([config["user"], config["password"], config["database"]]):
            raise ValueError(
                "Missing required config. Set MSSQL_CONNECTION_STRING or "
                "MSSQL_USER, MSSQL_PASSWORD, MSSQL_DATABASE"
            )

    return config

def get_command():
    """Get the command to execute SQL queries."""
    return os.getenv("MSSQL_COMMAND", "execute_sql")

def is_select_query(query: str) -> bool:
    """
    Check if a query is a SELECT statement, accounting for comments.
    Handles both single-line (--) and multi-line (/* */) SQL comments.
    """
    # Remove multi-line comments /* ... */
    query_cleaned = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)
    
    # Remove single-line comments -- ...
    lines = query_cleaned.split('\n')
    cleaned_lines = []
    for line in lines:
        # Find -- comment marker and remove everything after it
        comment_pos = line.find('--')
        if comment_pos != -1:
            line = line[:comment_pos]
        cleaned_lines.append(line)
    
    query_cleaned = '\n'.join(cleaned_lines)
    
    # Get the first non-empty word after stripping whitespace
    first_word = query_cleaned.strip().split()[0] if query_cleaned.strip() else ""
    return first_word.upper() == "SELECT"

# Initialize server
app = Server("mssql_mcp_server")

@app.list_resources()
async def list_resources() -> list[Resource]:
    """List SQL Server tables as resources."""
    config = get_db_config()
    try:
        conn = pymssql.connect(**config)
        cursor = conn.cursor()
        # Query to get user tables from the current database
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
        """)
        tables = cursor.fetchall()
        logger.info(f"Found tables: {tables}")
        
        resources = []
        for table in tables:
            resources.append(
                Resource(
                    uri=f"mssql://{table[0]}/data",
                    name=f"Table: {table[0]}",
                    mimeType="text/plain",
                    description=f"Data in table: {table[0]}"
                )
            )
        cursor.close()
        conn.close()
        return resources
    except Exception as e:
        logger.error(f"Failed to list resources: {str(e)}")
        return []

@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    """Read table contents."""
    config = get_db_config()
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")
    
    if not uri_str.startswith("mssql://"):
        raise ValueError(f"Invalid URI scheme: {uri_str}")
        
    parts = uri_str[8:].split('/')
    table = parts[0]
    
    try:
        # Validate table name to prevent SQL injection
        safe_table = validate_table_name(table)
        
        conn = pymssql.connect(**config)
        cursor = conn.cursor()
        # Use TOP 100 for MSSQL (equivalent to LIMIT in MySQL)
        cursor.execute(f"SELECT TOP 100 * FROM {safe_table}")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        result = [",".join(map(str, row)) for row in rows]
        cursor.close()
        conn.close()
        return "\n".join([",".join(columns)] + result)
                
    except Exception as e:
        logger.error(f"Database error reading resource {uri}: {str(e)}")
        raise RuntimeError(f"Database error: {str(e)}")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available SQL Server tools."""
    command = get_command()
    logger.info("Listing tools...")
    return [
        Tool(
            name=command,
            description="Execute an SQL query on the SQL Server",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute"
                    }
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute SQL commands."""
    config = get_db_config()
    command = get_command()
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    
    if name != command:
        raise ValueError(f"Unknown tool: {name}")
    
    query = arguments.get("query")
    if not query:
        raise ValueError("Query is required")
    
    try:
        conn = pymssql.connect(**config)
        cursor = conn.cursor()
        cursor.execute(query)
        
        # Special handling for table listing
        if is_select_query(query) and "INFORMATION_SCHEMA.TABLES" in query.upper():
            tables = cursor.fetchall()
            result = ["Tables_in_" + config["database"]]  # Header
            result.extend([table[0] for table in tables])
            cursor.close()
            conn.close()
            return [TextContent(type="text", text="\n".join(result))]
        
        # Regular SELECT queries
        elif is_select_query(query):
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            result = [",".join(map(str, row)) for row in rows]
            cursor.close()
            conn.close()
            return [TextContent(type="text", text="\n".join([",".join(columns)] + result))]
        
        # Non-SELECT queries
        else:
            conn.commit()
            affected_rows = cursor.rowcount
            cursor.close()
            conn.close()
            return [TextContent(type="text", text=f"Query executed successfully. Rows affected: {affected_rows}")]
                
    except Exception as e:
        logger.error(f"Error executing SQL '{query}': {e}")
        return [TextContent(type="text", text=f"Error executing query: {str(e)}")]

def _get_api_key() -> str:
    """Load the API key from the environment. Fail fast if not set."""
    key = os.getenv("MCP_API_KEY")
    if not key:
        raise RuntimeError(
            "MCP_API_KEY environment variable is required. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return key


def create_starlette_app(mcp_server: Server) -> Starlette:
    """
    Build a Starlette ASGI app that exposes the MCP server over SSE.
    All SSE and message endpoints are protected by an API key check.
    """
    api_key = _get_api_key()
    sse_transport = SseServerTransport("/messages/")

    def _check_api_key(request: Request) -> bool:
        provided = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        return secrets.compare_digest(provided or "", api_key)

    async def handle_sse(request: Request) -> Response:
        if not _check_api_key(request):
            return Response("Unauthorized", status_code=401)
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0], streams[1], mcp_server.create_initialization_options()
            )
        return Response()

    async def handle_messages(request: Request) -> Response:
        if not _check_api_key(request):
            return Response("Unauthorized", status_code=401)
        await sse_transport.handle_post_message(request.scope, request.receive, request._send)
        return Response()

    async def health(request: Request) -> Response:
        return Response('{"status":"ok"}', media_type="application/json")

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/sse", handle_sse),
            Mount("/messages/", app=handle_messages),
        ]
    )


async def main():
    """Main entry point — starts HTTP/SSE server (for Azure Container Apps / AI Foundry)."""
    import uvicorn

    logger.info("Starting MSSQL MCP server (HTTP/SSE mode)...")

    # Validate DB config early so we fail fast at startup, not on first request
    config = get_db_config()
    server_info = f"{config['server']}:{config.get('port', 1433)}"
    user_info = config.get("user", "Windows Auth")
    logger.info(f"Database: {server_info}/{config['database']} as {user_info}")

    starlette_app = create_starlette_app(app)

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Listening on {host}:{port}")

    config_uvicorn = uvicorn.Config(starlette_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config_uvicorn)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
