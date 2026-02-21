from django.apps import AppConfig


class TodosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.todos"
    # name = "apps.todos" → label automático = "todos" → tabla = "todos_todo"
