# messaging/urls.py
from django.urls import path
from .views import (
    ConversationListView,
    ConversationStartView,
    MessageListView,
    MessageSendView,
)

urlpatterns = [
    path('',                     ConversationListView.as_view()),
    path('start/',               ConversationStartView.as_view()),
    path('<int:conv_id>/',       MessageListView.as_view()),
    path('<int:conv_id>/send/',  MessageSendView.as_view()),
]