"""RAG parts of Ask NOP: store.py (the Qdrant connection), warehouse.py (read-only MySQL ai_gold),
sql_guard.py (is this SQL safe to run?), agent.py (question -> SQL -> rows -> answer).
The AI calls, the embeddings, the docs chunks and the notes search are LangChain: portal/lc/."""
