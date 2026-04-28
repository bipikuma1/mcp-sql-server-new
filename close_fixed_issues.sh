#!/bin/bash

# Script to close fixed issues with appropriate comments

echo "Closing fixed issues..."

# Issue #8: Support MSSQL_PORT
echo "Closing issue #8: Support MSSQL_PORT"
gh issue close 8 --comment "This has been implemented! You can now use the \`MSSQL_PORT\` environment variable:

\`\`\`bash
MSSQL_PORT=1433  # Or any custom port
\`\`\`

The implementation includes:
- Default port of 1433 if not specified
- Proper integer conversion with error handling
- Full support for non-standard SQL Server ports

See the updated README for configuration examples."

# Issue #7: Windows Authentication
echo "Closing issue #7: Windows Authentication"
gh issue close 7 --comment "Windows Authentication is now fully supported! Simply set:

\`\`\`bash
MSSQL_WINDOWS_AUTH=true
\`\`\`

When enabled:
- No need to provide MSSQL_USER or MSSQL_PASSWORD
- The server will use Windows integrated authentication
- Works with both standard SQL Server and LocalDB

See the README for complete configuration examples."

# Issue #6: SQL Local DB
echo "Closing issue #6: SQL Local DB"
gh issue close 6 --comment "LocalDB support has been implemented! The server now automatically detects and handles LocalDB connections:

\`\`\`bash
MSSQL_SERVER=(localdb)\\MSSQLLocalDB
MSSQL_DATABASE=your_database
MSSQL_WINDOWS_AUTH=true  # LocalDB typically uses Windows Auth
\`\`\`

The implementation automatically converts LocalDB format to pymssql-compatible format."

# Issue #11: Azure SQL encryption
echo "Closing issue #11: Azure SQL encryption"
gh issue close 11 --comment "Azure SQL Database connections are now fully supported with automatic encryption handling!

The server automatically:
- Detects Azure SQL connections (by checking for \`.database.windows.net\`)
- Enables encryption automatically for Azure SQL
- Sets the required TDS version (7.4)

For non-Azure connections, you can control encryption with:
\`\`\`bash
MSSQL_ENCRYPT=true  # or false
\`\`\`

See the README for Azure SQL configuration examples."

# Issue #4: Docker support
echo "Closing issue #4: Docker support"
gh issue close 4 --comment "Docker support has been added! The repository now includes:

- \`Dockerfile\` for containerizing the MCP server
- \`docker-compose.yml\` with SQL Server 2019 for testing
- Comprehensive \`Makefile\` with Docker commands

Quick start:
\`\`\`bash
make docker-build
make docker-up
\`\`\`

See the README for complete Docker documentation."

# Issue #12: MSSQL_SERVER configuration
echo "Closing issue #12: MSSQL_SERVER configuration"
gh issue close 12 --comment "This issue has been resolved! The server now:

1. Properly reads the \`MSSQL_SERVER\` environment variable
2. Logs the server being used for debugging
3. Only defaults to \"localhost\" if MSSQL_SERVER is not set

The fix includes enhanced logging to help debug connection issues. If you're still experiencing problems, please check that the environment variable is properly set in your configuration."

echo "Done! Fixed issues have been closed."