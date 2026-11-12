from django.urls import path, re_path

from . import api, views

urlpatterns = [
    # the JSON API of the website (the React app in frontend/) - see api.py
    path("api/csrf", api.csrf, name="api_csrf"),
    path("api/login", api.sign_in, name="api_login"),
    path("api/logout", api.sign_out, name="api_logout"),
    path("api/me", api.me, name="api_me"),
    path("api/home", api.home_page, name="api_home"),  # the Home page: KPIs, tables, connections (every user)
    path("api/chats", api.chats, name="api_chats"),  # the chat list and the removed chats
    path("api/chats/<int:chat_id>", api.chat_detail, name="api_chat"),
    path("api/chats/<int:chat_id>/rename", api.chat_rename, name="api_chat_rename"),
    path("api/chats/<int:chat_id>/remove", api.chat_remove, name="api_chat_remove"),    # hide from the list
    path("api/chats/<int:chat_id>/restore", api.chat_restore, name="api_chat_restore"),
    path("api/chats/<int:chat_id>/delete", api.chat_delete, name="api_chat_delete"),    # for good, with its questions
    path("api/ask", api.ask, name="api_ask"),
    path("api/ask/stream", api.ask_stream, name="api_ask_stream"),  # the same, streamed while it runs
    path("api/questions/<int:pk>", api.question_detail, name="api_question"),  # one saved answer (no AI call)
    path("api/questions/<int:pk>/rows", api.question_rows, name="api_rows"),
    path("api/questions/<int:pk>/excel", api.question_excel, name="api_excel"),
    path("api/questions/<int:pk>/chart", api.question_chart, name="api_chart"),  # a chart made by the AI (tokens)
    path("api/questions/<int:pk>/edit", api.question_edit, name="api_edit"),  # ask an edited version
    path("api/questions/<int:pk>/again", api.question_again, name="api_again"),  # History's "Ask again"
    path("api/history", api.history, name="api_history"),
    path("api/memories", api.memories, name="api_memories"),  # the user's saved memories: list / add one
    path("api/memories/delete-all", api.memory_delete_all, name="api_memories_delete_all"),
    path("api/memories/<int:memory_id>/delete", api.memory_delete, name="api_memory_delete"),
    path("api/documents", api.documents, name="api_documents"),  # what the AI can read (staff)
    path("api/data", api.data_tables, name="api_data"),  # records in each MySQL table (staff)
    path("api/users", api.users, name="api_users"),  # list / add people (staff)
    path("api/users/<int:user_id>", api.user_detail, name="api_user"),
    path("api/users/<int:user_id>/active", api.user_active, name="api_user_active"),
    path("api/users/<int:user_id>/password", api.user_password, name="api_user_password"),
    path("api/audit", api.audit_log, name="api_audit"),  # who did what and when (staff, read-only)
    path("api/graph/search", api.graph_search, name="api_graph_search"),  # the Knowledge graph (every user)
    path("api/graph/node", api.graph_node, name="api_graph_node"),
    path("api/graph/similar", api.graph_similar, name="api_graph_similar"),
    re_path(r"^api(?:/(?P<rest>.*))?$", api.not_found),  # any other API address: JSON 404
    # every other address (not the admin, not a static file) is a page of the React app
    path("", views.react_app, name="react_app"),
    re_path(r"^(?!(?:admin|static|api)(?:/|$))(?P<rest>.+)$", views.react_app),
]
