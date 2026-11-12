"""LangChain step C: the prompts as LangChain templates (ChatPromptTemplate).

The texts are read from agent.py (its prompt constants), never copied: they stay next to the rules
and checks they belong to. The {fields} are what agent.py fills in, e.g. SQL_PROMPT needs schema,
count, documents, today, preferences, earlier and question (the sql_values of graph.pick_schema).
{preferences} = the user's saved memories (agent.preferences) in the SQL, answer and documents requests;
'' when the user has none, so those requests are then exactly as before the memory.
"""
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate

from ..rag import agent

# question -> SQL. "retries" = the earlier tries of this question: the AI's reply + "That did not work: ..."
SQL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", agent.SQL_SYSTEM_PROMPT),
    ("human", agent.SQL_REQUEST),
    MessagesPlaceholder("retries", optional=True),
])

# the text sent after a failed try (the guard refused it, MySQL failed, a check found a mistake)
RETRY_PROMPT = PromptTemplate.from_template(agent.RETRY_PROMPT)

# a follow-up ("and for Sep?") written out as a full question, from the chat's earlier questions
REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", agent.REWRITE_SYSTEM_PROMPT),
    ("human", agent.REWRITE_REQUEST),
])

# the rows -> a short plain-English answer
EXPLAIN_PROMPT = ChatPromptTemplate.from_messages([
    ("system", agent.EXPLAIN_SYSTEM_PROMPT),
    ("human", agent.EXPLAIN_REQUEST),
])

# step H, the router: the question + the closest PDF pieces -> one word, data or documents
ROUTE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", agent.ROUTE_SYSTEM_PROMPT),
    ("human", agent.ROUTE_REQUEST),
])

# step H, a document question: the closest PDF pieces -> a short answer (or NOT_IN_DOCUMENTS: why)
DOCS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", agent.DOCS_SYSTEM_PROMPT),
    ("human", agent.DOCS_REQUEST),
])
