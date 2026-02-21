from django.test import TestCase
from apps.todos.models import Todo


class TodoModelTest(TestCase):

    def setUp(self):
        self.todo = Todo.objects.create(
            title="Test todo",
            description="Test description",
            completed=False,
        )

    def test_todo_creation(self):
        self.assertEqual(self.todo.title, "Test todo")
        self.assertEqual(self.todo.description, "Test description")
        self.assertFalse(self.todo.completed)

    def test_todo_str(self):
        self.assertEqual(str(self.todo), "Test todo")

    def test_todo_default_completed_is_false(self):
        todo = Todo.objects.create(title="Sin completar")
        self.assertFalse(todo.completed)

    def test_todo_has_created_at(self):
        self.assertIsNotNone(self.todo.created_at)

    def test_todo_has_updated_at(self):
        self.assertIsNotNone(self.todo.updated_at)

    def test_todo_ordering_newest_first(self):
        second = Todo.objects.create(title="Second todo")
        todos = Todo.objects.all()
        self.assertEqual(todos[0], second)
        self.assertEqual(todos[1], self.todo)
