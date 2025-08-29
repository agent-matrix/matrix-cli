matrix install "mcp_server:watsonx-agent@0.1.0" --alias "watsonx-chat" --hub "https://api.matrixhub.io"

matrix ps

matrix mcp call chat --url "http://127.0.0.1:6289/sse" --args '{"query":"Tell me about Genoa"}'

matrix stop "watsonx-chat"

matrix uninstall "watsonx-chat" -y