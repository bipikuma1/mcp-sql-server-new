#!/usr/bin/env python
"""Test SQL Server connection using the same configuration as the MCP server."""

import os
import sys
import pymssql

# Add src to path to import our server module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from mssql_mcp_server.server import get_db_config

try:
    print("Loading database configuration from environment variables...")
    config = get_db_config()
    
    # Mask sensitive information for display
    display_config = config.copy()
    if 'password' in display_config:
        display_config['password'] = '***'
    print(f"Configuration: {display_config}")
    
    print("\nAttempting to connect to SQL Server...")
    conn = pymssql.connect(**config)
    cursor = conn.cursor()
    print("Connection successful!")
    
    print("\nTesting query execution...")
    cursor.execute("SELECT TOP 5 TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
    rows = cursor.fetchall()
    print(f"Found {len(rows)} tables:")
    for row in rows:
        print(f"  - {row[0]}")
    
    cursor.close()
    conn.close()
    print("\nConnection test completed successfully!")
except Exception as e:
    print(f"Error: {str(e)}")
    import traceback
    traceback.print_exc()
