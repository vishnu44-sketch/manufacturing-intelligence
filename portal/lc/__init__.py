"""The LangChain parts of Ask NOP: every AI call, the embeddings, the docs chunks and the notes search.

LangChain does the LLM calls (llm.py, prompts.py, chains.py, calls.py), the embeddings (embeddings.py), the
docs chunks (docs.py), the notes in Qdrant (vectorstore.py) and the PDFs (pdfs.py). Our own code in
portal/rag/ keeps the safety parts: the SQL guard (sql_guard.py), the read-only MySQL (warehouse.py), the
date rules, the backup model (agent.py) and the MCP server. The steps of one question - rewrite, route,
search, write SQL, check, run, retry, explain - are a LangGraph graph (graph.py).
"""
