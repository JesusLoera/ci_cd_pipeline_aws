from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.todos.models import Todo


class TodoAPITest(APITestCase):

    def setUp(self):
        self.todo = Todo.objects.create(
            title="API test todo",
            description="API test description",
            completed=False,
        )
        self.list_url = reverse("todo-list")
        self.detail_url = reverse("todo-detail", kwargs={"pk": self.todo.pk})

    # --- LIST ---

    def test_list_todos(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_returns_all_todos(self):
        Todo.objects.create(title="Second todo")
        response = self.client.get(self.list_url)
        self.assertEqual(response.data["count"], 2)

    # --- CREATE ---

    def test_create_todo(self):
        data = {"title": "New todo", "description": "New description", "completed": False}
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Todo.objects.count(), 2)

    def test_create_todo_without_title_fails(self):
        response = self.client.post(self.list_url, {"description": "No title"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_todo_only_title(self):
        response = self.client.post(self.list_url, {"title": "Solo titulo"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # --- RETRIEVE ---

    def test_retrieve_todo(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], self.todo.title)

    def test_retrieve_nonexistent_todo(self):
        url = reverse("todo-detail", kwargs={"pk": 9999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- UPDATE ---

    def test_update_todo(self):
        data = {"title": "Updated", "description": "Updated desc", "completed": True}
        response = self.client.put(self.detail_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Updated")
        self.assertTrue(self.todo.completed)

    def test_partial_update_todo(self):
        response = self.client.patch(self.detail_url, {"completed": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.todo.refresh_from_db()
        self.assertTrue(self.todo.completed)

    # --- DELETE ---

    def test_delete_todo(self):
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Todo.objects.count(), 0)

    # --- FIELDS ---

    def test_response_contains_expected_fields(self):
        response = self.client.get(self.detail_url)
        self.assertIn("id", response.data)
        self.assertIn("title", response.data)
        self.assertIn("description", response.data)
        self.assertIn("completed", response.data)
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
