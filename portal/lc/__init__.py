"""The LangChain version of the pipeline, used when .env says USE_LANGCHAIN=on (switch.py).

Built step by step next to portal/rag/ (the classic version, the default), so both can be compared.
LangChain does the LLM calls, the prompts and the document search; our own code keeps the safety
parts: the SQL guard (rag/sql_guard.py), the read-only MySQL (rag/warehouse.py), the date rules,
the retry loop and the MCP server.
"""
