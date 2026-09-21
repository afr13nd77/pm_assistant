"""TODO CRUD endpoints: чтение, создание и обновление личных TODO-задач в vault."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..vault_cache import _cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Todos"])


class TodoCreateRequest(BaseModel):
    title: str
    due_date: str | None = None
    context: str | None = None


class TodoUpdateRequest(BaseModel):
    status: str
    result: str | None = None


# ---------------------------------------------------------------------------
# TODO CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v1/todos")
async def get_todos(status: str = "open"):
    """Получить список TODO-задач с фильтрацией по статусу."""
    logger.info(f"GET /todos — start, status={status}")
    try:
        cache_key = f"todos:{status}"
        cached = _cache.get(cache_key)
        if cached is not None:
            logger.info(f"GET /todos — returning cached, status={status}")
            return cached

        from shared.vault_paths import wiki_todos

        from ..today_parsers import parse_todos

        todo_path = wiki_todos()
        if not todo_path.exists():
            result = {"count": 0, "todos": []}
            _cache.set(cache_key, result)
            logger.info(f"GET /todos — file not found, returning empty, status={status}")
            return result

        text = todo_path.read_text(encoding="utf-8")
        logger.info(f"GET /todos — read {len(text)} chars from {todo_path.name}")
        all_todos = parse_todos(text)

        if status == "open":
            filtered = [t for t in all_todos if t["status"] in ("todo", "in-progress")]
        elif status == "done":
            filtered = [t for t in all_todos if t["status"] in ("done", "cancelled")]
        else:  # "all"
            filtered = all_todos

        result = {"count": len(filtered), "todos": filtered}
        _cache.set(cache_key, result)
        logger.info(f"GET /todos — success, count={len(filtered)}")
        return result
    except Exception as e:
        logger.error(f"GET /todos — error: {e}")
        raise HTTPException(status_code=500, detail="Failed to read TODOs")


@router.post("/api/v1/todos", status_code=201)
async def create_todo(req: TodoCreateRequest):
    """Создать новый TODO в vault."""
    logger.info(f"POST /todos — start, title={req.title[:50]}")
    try:
        if not req.title.strip():
            logger.warning("POST /todos — empty title rejected")
            raise HTTPException(status_code=400, detail="Title is required")

        import re
        from datetime import date

        from shared.file_writer import atomic_write, file_lock
        from shared.vault_paths import wiki_todos

        from ..today_parsers import format_todo_block

        todo_path = wiki_todos()

        # Ensure parent dir exists
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"POST /todos — todo_path={todo_path}")

        if todo_path.exists():
            text = todo_path.read_text(encoding="utf-8")
            logger.info(f"POST /todos — read existing file, {len(text)} chars")
        else:
            text = "---\ntype: personal-todo\nowner: '@igor'\n---\n\n## Открытые задачи\n\n## Закрытые задачи\n"
            logger.info("POST /todos — file not found, using template")

        # Find max TODO-NNN
        ids = [int(m) for m in re.findall(r"\[TODO-(\d+)\]", text)]
        next_num = max(ids) + 1 if ids else 1
        todo_id = f"TODO-{next_num:03d}"
        logger.info(f"POST /todos — generated id={todo_id}")

        # Format date for display
        created = date.today().strftime("%d.%m.%Y")
        due_display = None
        if req.due_date:
            # Input is ISO YYYY-MM-DD, display as DD.MM.YYYY
            parts = req.due_date.split("-")
            if len(parts) == 3:
                due_display = f"{parts[2]}.{parts[1]}.{parts[0]}"

        block = format_todo_block(
            todo_id=todo_id,
            title=req.title.strip(),
            status="todo",
            created=created,
            due_date=due_display,
            context=req.context,
            result=None,
        )
        logger.info(f"POST /todos — formatted block for {todo_id}")

        # Insert before "## Закрытые задачи" or at end
        closed_marker = "## Закрытые задачи"
        if closed_marker in text:
            idx = text.index(closed_marker)
            new_text = text[:idx] + block + "\n" + text[idx:]
        else:
            new_text = text + "\n" + block

        with file_lock(todo_path):
            atomic_write(todo_path, new_text)
        logger.info(f"POST /todos — file written for {todo_id}")

        _cache.invalidate("todos")

        result = {
            "id": todo_id,
            "title": req.title.strip(),
            "status": "todo",
            "created": date.today().isoformat(),
            "due_date": req.due_date,
        }
        logger.info(f"POST /todos — success, created {todo_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /todos — error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create TODO")


@router.patch("/api/v1/todos/{todo_id}")
async def update_todo(todo_id: str, req: TodoUpdateRequest):
    """Обновить статус существующего TODO."""
    logger.info(f"PATCH /todos/{todo_id} — start, status={req.status}")
    try:
        valid_statuses = {"todo", "in-progress", "done", "cancelled"}
        if req.status not in valid_statuses:
            logger.warning(f"PATCH /todos/{todo_id} — invalid status={req.status}")
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {', '.join(sorted(valid_statuses))}",
            )

        import re
        from datetime import date

        from shared.file_writer import atomic_write, file_lock
        from shared.vault_paths import wiki_todos

        todo_path = wiki_todos()
        if not todo_path.exists():
            logger.warning(f"PATCH /todos/{todo_id} — file not found")
            raise HTTPException(status_code=404, detail=f"{todo_id} not found")

        text = todo_path.read_text(encoding="utf-8")
        logger.info(f"PATCH /todos/{todo_id} — read {len(text)} chars")

        # Find the section ### [TODO-NNN]
        section_pattern = rf"(### \[{re.escape(todo_id)}\] .+?)(?=### \[TODO-|\Z)"
        match = re.search(section_pattern, text, re.DOTALL)
        if not match:
            logger.warning(f"PATCH /todos/{todo_id} — section not found in file")
            raise HTTPException(status_code=404, detail=f"{todo_id} not found")

        section = match.group(1)
        new_section = section

        # Update status
        new_section = re.sub(
            r"\*\*Статус:\*\*\s*.+",
            f"**Статус:** {req.status}",
            new_section,
        )
        logger.info(f"PATCH /todos/{todo_id} — status updated to {req.status}")

        # Add closed date if done/cancelled
        if req.status in ("done", "cancelled"):
            closed_date = date.today().strftime("%d.%m.%Y")
            if "**Закрыто:**" not in new_section:
                # Insert after **Статус:** line
                new_section = re.sub(
                    r"(\*\*Статус:\*\* .+)",
                    rf"\1\n**Закрыто:** {closed_date}",
                    new_section,
                )
                logger.info(f"PATCH /todos/{todo_id} — added closed date {closed_date}")
            else:
                new_section = re.sub(
                    r"\*\*Закрыто:\*\*\s*.+",
                    f"**Закрыто:** {closed_date}",
                    new_section,
                )
                logger.info(f"PATCH /todos/{todo_id} — updated closed date {closed_date}")

        # Add result if provided
        if req.result:
            if "**Результат:**" not in new_section:
                new_section = new_section.rstrip() + f"\n**Результат:** {req.result}\n"
                logger.info(f"PATCH /todos/{todo_id} — added result")
            else:
                new_section = re.sub(
                    r"\*\*Результат:\*\*\s*.+",
                    f"**Результат:** {req.result}",
                    new_section,
                )
                logger.info(f"PATCH /todos/{todo_id} — updated result")

        new_text = text.replace(section, new_section)

        with file_lock(todo_path):
            atomic_write(todo_path, new_text)
        logger.info(f"PATCH /todos/{todo_id} — file written")

        _cache.invalidate("todos")

        result = {
            "id": todo_id,
            "status": req.status,
            "closed": date.today().isoformat() if req.status in ("done", "cancelled") else None,
        }
        logger.info(f"PATCH /todos/{todo_id} — success")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PATCH /todos/{todo_id} — error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update {todo_id}")
