"""Integration tests for TODO CRUD endpoints (GET/POST/PATCH /api/v1/todos).

Uses TestClient with a temporary vault directory to test:
- GET /api/v1/todos with status filtering
- POST /api/v1/todos to create new TODO items
- PATCH /api/v1/todos/{todo_id} to update status
"""

from pathlib import Path
from unittest.mock import patch

import pytest


SAMPLE_TODO_MD = """\
---
type: personal-todo
owner: '@igor'
---

## Открытые задачи

### [TODO-001] Первая задача
**Статус:** todo
**Создано:** 15.07.2026
**Срок:** 30.07.2026
**Контекст:** Тестовый контекст

### [TODO-002] Вторая задача в работе
**Статус:** in-progress
**Создано:** 16.07.2026

## Закрытые задачи

### [TODO-003] Завершённая задача
**Статус:** done
**Создано:** 10.07.2026
**Закрыто:** 14.07.2026
**Результат:** Сделано успешно
"""


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault directory with TODO file."""
    todo_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
    todo_dir.mkdir(parents=True)
    todo_file = todo_dir / "todo.md"
    todo_file.write_text(SAMPLE_TODO_MD, encoding="utf-8")
    return tmp_path


@pytest.fixture
def vault_dir_empty(tmp_path):
    """Create a temporary vault directory without TODO file."""
    todo_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
    todo_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def client(vault_dir):
    """Create a FastAPI test client with vault_paths pointing to temp directory."""
    # Import module first so patch can find attributes
    import app.vault_api  # noqa: F401

    with patch("shared.vault_paths.VAULT_PATH", vault_dir), \
         patch("app.vault_api.VAULT_PATH", vault_dir):
        from fastapi.testclient import TestClient

        from app.vault_api import _cache, app
        _cache.invalidate()
        yield TestClient(app)


@pytest.fixture
def client_empty(vault_dir_empty):
    """Create a FastAPI test client with no TODO file."""
    import app.vault_api  # noqa: F401

    with patch("shared.vault_paths.VAULT_PATH", vault_dir_empty), \
         patch("app.vault_api.VAULT_PATH", vault_dir_empty):
        from fastapi.testclient import TestClient

        from app.vault_api import _cache, app
        _cache.invalidate()
        yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/todos
# ---------------------------------------------------------------------------


class TestGetTodos:

    def test_get_open_todos_default(self, client):
        """Should return only open (todo + in-progress) items by default."""
        resp = client.get("/api/v1/todos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        ids = [t["id"] for t in data["todos"]]
        assert "TODO-001" in ids
        assert "TODO-002" in ids

    def test_get_done_todos(self, client):
        """Should return only done/cancelled items when status=done."""
        resp = client.get("/api/v1/todos?status=done")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["todos"][0]["id"] == "TODO-003"

    def test_get_all_todos(self, client):
        """Should return all items when status=all."""
        resp = client.get("/api/v1/todos?status=all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

    def test_get_todos_empty_file(self, client_empty):
        """Should return empty list when todo.md doesn't exist."""
        resp = client_empty.get("/api/v1/todos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["todos"] == []

    def test_get_todos_cached(self, client):
        """Second call should return cached results."""
        resp1 = client.get("/api/v1/todos")
        assert resp1.status_code == 200
        resp2 = client.get("/api/v1/todos")
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()


# ---------------------------------------------------------------------------
# POST /api/v1/todos
# ---------------------------------------------------------------------------


class TestCreateTodo:

    def test_create_todo_minimal(self, client, vault_dir):
        """Should create a TODO with just a title."""
        resp = client.post(
            "/api/v1/todos",
            json={"title": "Новая задача"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "TODO-004"  # max existing is 003
        assert data["title"] == "Новая задача"
        assert data["status"] == "todo"
        assert data["due_date"] is None

        # Verify file was updated
        todo_file = vault_dir / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        content = todo_file.read_text(encoding="utf-8")
        assert "[TODO-004] Новая задача" in content
        assert "**Статус:** todo" in content

    def test_create_todo_with_due_date(self, client, vault_dir):
        """Should create a TODO with due date converted to DD.MM.YYYY."""
        resp = client.post(
            "/api/v1/todos",
            json={"title": "Задача со сроком", "due_date": "2026-08-01"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["due_date"] == "2026-08-01"

        # Verify DD.MM.YYYY format in file
        todo_file = vault_dir / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        content = todo_file.read_text(encoding="utf-8")
        assert "**Срок:** 01.08.2026" in content

    def test_create_todo_with_context(self, client, vault_dir):
        """Should create a TODO with context field."""
        resp = client.post(
            "/api/v1/todos",
            json={"title": "Задача с контекстом", "context": "Для проекта X"},
        )
        assert resp.status_code == 201

        todo_file = vault_dir / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        content = todo_file.read_text(encoding="utf-8")
        assert "**Контекст:** Для проекта X" in content

    def test_create_todo_empty_title_rejected(self, client):
        """Should return 400 when title is empty or whitespace."""
        resp = client.post(
            "/api/v1/todos",
            json={"title": "   "},
        )
        assert resp.status_code == 400
        assert "Title is required" in resp.json()["detail"]

    def test_create_todo_inserted_before_closed_section(self, client, vault_dir):
        """New TODO should be inserted before 'Закрытые задачи' section."""
        client.post("/api/v1/todos", json={"title": "Новая"})

        todo_file = vault_dir / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        content = todo_file.read_text(encoding="utf-8")

        # New TODO should appear before closed marker
        new_pos = content.index("[TODO-004]")
        closed_pos = content.index("## Закрытые задачи")
        assert new_pos < closed_pos

    def test_create_todo_no_existing_file(self, client_empty, vault_dir_empty):
        """Should create todo.md from template when it doesn't exist."""
        resp = client_empty.post(
            "/api/v1/todos",
            json={"title": "Самая первая задача"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "TODO-001"

        todo_file = vault_dir_empty / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        assert todo_file.exists()
        content = todo_file.read_text(encoding="utf-8")
        assert "type: personal-todo" in content
        assert "[TODO-001] Самая первая задача" in content

    def test_create_todo_invalidates_cache(self, client):
        """Cache should be invalidated after creating a TODO."""
        # Fill cache
        client.get("/api/v1/todos")

        # Create new
        resp = client.post("/api/v1/todos", json={"title": "Новая"})
        assert resp.status_code == 201

        # Get should reflect new item
        resp2 = client.get("/api/v1/todos")
        data = resp2.json()
        ids = [t["id"] for t in data["todos"]]
        assert "TODO-004" in ids


# ---------------------------------------------------------------------------
# PATCH /api/v1/todos/{todo_id}
# ---------------------------------------------------------------------------


class TestUpdateTodo:

    def test_update_status_to_done(self, client, vault_dir):
        """Should update status to done and add closed date."""
        resp = client.patch(
            "/api/v1/todos/TODO-001",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "TODO-001"
        assert data["status"] == "done"
        assert data["closed"] is not None

        # Verify file
        todo_file = vault_dir / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        content = todo_file.read_text(encoding="utf-8")
        # Find the TODO-001 section and verify status
        section_start = content.index("[TODO-001]")
        section_text = content[section_start:section_start + 200]
        assert "**Статус:** done" in section_text
        assert "**Закрыто:**" in section_text

    def test_update_status_to_in_progress(self, client):
        """Should update status to in-progress without adding closed date."""
        resp = client.patch(
            "/api/v1/todos/TODO-001",
            json={"status": "in-progress"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "in-progress"
        assert data["closed"] is None

    def test_update_with_result(self, client, vault_dir):
        """Should add result field when provided."""
        resp = client.patch(
            "/api/v1/todos/TODO-001",
            json={"status": "done", "result": "Задача выполнена полностью"},
        )
        assert resp.status_code == 200

        todo_file = vault_dir / "wiki" / "domains" / "general" / "tasks" / "todo.md"
        content = todo_file.read_text(encoding="utf-8")
        assert "**Результат:** Задача выполнена полностью" in content

    def test_update_invalid_status(self, client):
        """Should return 400 for invalid status value."""
        resp = client.patch(
            "/api/v1/todos/TODO-001",
            json={"status": "invalid-status"},
        )
        assert resp.status_code == 400
        assert "Status must be one of" in resp.json()["detail"]

    def test_update_nonexistent_todo(self, client):
        """Should return 404 for non-existent TODO id."""
        resp = client.patch(
            "/api/v1/todos/TODO-999",
            json={"status": "done"},
        )
        assert resp.status_code == 404
        assert "TODO-999 not found" in resp.json()["detail"]

    def test_update_no_file(self, client_empty):
        """Should return 404 when todo.md doesn't exist."""
        resp = client_empty.patch(
            "/api/v1/todos/TODO-001",
            json={"status": "done"},
        )
        assert resp.status_code == 404

    def test_update_invalidates_cache(self, client):
        """Cache should be invalidated after updating a TODO."""
        # Fill cache
        resp1 = client.get("/api/v1/todos")
        assert resp1.json()["count"] == 2

        # Update to done
        client.patch("/api/v1/todos/TODO-001", json={"status": "done"})

        # Get should reflect update
        resp2 = client.get("/api/v1/todos")
        data = resp2.json()
        ids = [t["id"] for t in data["todos"]]
        assert "TODO-001" not in ids  # No longer open

    def test_update_cancelled(self, client):
        """Should handle cancelled status with closed date."""
        resp = client.patch(
            "/api/v1/todos/TODO-002",
            json={"status": "cancelled"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["closed"] is not None
