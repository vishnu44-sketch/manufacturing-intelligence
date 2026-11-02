from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    # the home address just opens Ask NOP
    path("", RedirectView.as_view(pattern_name="ask"), name="home"),
    path("ask/", views.ask, name="ask"),  # GET: the latest chat; POST: a new chat with the question
    path("ask/new/", views.ask_new, name="ask_new"),  # the empty "New chat" screen
    path("ask/c/<int:chat_id>/", views.ask_chat, name="ask_chat"),  # one chat (GET) / ask in it (POST)
    path("ask/c/<int:chat_id>/rename/", views.chat_rename, name="chat_rename"),
    path("ask/c/<int:chat_id>/remove/", views.chat_remove, name="chat_remove"),    # hide from the list
    path("ask/c/<int:chat_id>/restore/", views.chat_restore, name="chat_restore"),
    path("ask/c/<int:chat_id>/delete/", views.chat_delete, name="chat_delete"),    # for good, with its questions
    path("ask/<int:pk>/", views.ask_result, name="ask_result"),  # one saved answer (no AI call)
    path("ask/<int:pk>/excel/", views.ask_excel, name="ask_excel"),
    path("ask/<int:pk>/edit/", views.question_edit, name="question_edit"),  # ask an edited version (POST)
    path("history/", views.history, name="history"),
    path("users/", views.users, name="users"),
    path("documents/", views.documents, name="documents"),  # what the AI can read (staff)
    path("data/", views.data_tables, name="data"),  # records in each MySQL table (staff)
]
