"""LangChain step C: the prompts as LangChain templates (ChatPromptTemplate).

The texts are read from the classic agent.py, never copied: a better prompt there is a better prompt
in both versions. The {fields} are the same, e.g. SQL_PROMPT needs schema, count, documents, today,
earlier and question - exactly what agent._answer() fills in today.
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
