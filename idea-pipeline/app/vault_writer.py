import json
import logging
from datetime import date, datetime
from pathlib import Path

import frontmatter
from shared import vault_paths
from slugify import slugify

from shared.file_writer import atomic_write

logger = logging.getLogger(__name__)


def get_pipeline_context(slug: str, domain: str) -> dict:
    """Return a dict with all target directories for a pipeline run.

    Replaces the old ``create_pipeline_dir`` which created a single
    ``Pipeline/<date>-<slug>/`` directory.  Each artifact type now has
    its own domain-based directory resolved via ``vault_paths``.
    """
    clean_slug = slugify(slug, allow_unicode=True)
    context = {
        "domain": domain,
        "slug": clean_slug,
        "ideas_dir": vault_paths.wiki_domain_dir(domain, "ideas"),
        "prds_dir": vault_paths.wiki_domain_dir(domain, "prds"),
        "epics_dir": vault_paths.wiki_domain_dir(domain, "epics"),
        "tasks_dir": vault_paths.wiki_domain_dir(domain, "tasks"),
        "raw_dir": vault_paths.raw_ideas(),
    }
    logger.info(
        "get_pipeline_context: domain=%s, slug=%s, ideas_dir=%s, prds_dir=%s, "
        "epics_dir=%s, tasks_dir=%s, raw_dir=%s",
        domain,
        clean_slug,
        context["ideas_dir"],
        context["prds_dir"],
        context["epics_dir"],
        context["tasks_dir"],
        context["raw_dir"],
    )
    return context


def write_input(
    text: str,
    pipeline_id: str,
    input_type: str,
    slug: str,
    domain: str,
    source_file: str = "",
) -> Path:
    """Write the raw user input to ``raw/inbound/ideas/<date>-<slug>-input.md``."""
    clean_slug = slugify(slug, allow_unicode=True)
    today = date.today().isoformat()
    filename = f"{today}-{clean_slug}-input.md"

    metadata = {
        "pipeline_id": pipeline_id,
        "domain": domain,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_type": input_type,
        "source_file": source_file,
        "tags": ["pipeline", "input"],
    }
    post = frontmatter.Post(text, **metadata)
    content = frontmatter.dumps(post)

    filepath = vault_paths.raw_ideas() / filename
    atomic_write(filepath, content)
    size = len(content.encode("utf-8"))
    logger.info("Written input: %s, size=%d bytes", filepath, size)
    return filepath


def _inject_frontmatter(
    content: str, pipeline_id: str, model: str, domain: str,
) -> str:
    """Inject ``pipeline_id``, ``model``, and ``domain`` into frontmatter."""
    try:
        post = frontmatter.loads(content)
        post.metadata["pipeline_id"] = pipeline_id
        post.metadata["model"] = model
        post.metadata["domain"] = domain
        return frontmatter.dumps(post)
    except Exception as exc:
        logger.warning(
            "Frontmatter injection failed, writing content as-is: %s", exc,
        )
        return content


def write_analysis(
    content: str,
    pipeline_id: str,
    model: str,
    slug: str,
    domain: str,
) -> Path:
    """Write analysis to ``wiki/domains/<domain>/ideas/<date>-<slug>-analysis.md``."""
    clean_slug = slugify(slug, allow_unicode=True)
    today = date.today().isoformat()
    filename = f"{today}-{clean_slug}-analysis.md"

    result = _inject_frontmatter(content, pipeline_id, model, domain)
    filepath = vault_paths.wiki_domain_dir(domain, "ideas") / filename
    atomic_write(filepath, result)
    size = len(result.encode("utf-8"))
    logger.info("Written analysis: %s, size=%d bytes", filepath, size)
    return filepath


def write_prd(
    content: str,
    pipeline_id: str,
    model: str,
    slug: str,
    domain: str,
) -> Path:
    """Write PRD to ``wiki/domains/<domain>/prds/<date>-<slug>-prd.md``."""
    clean_slug = slugify(slug, allow_unicode=True)
    today = date.today().isoformat()
    filename = f"{today}-{clean_slug}-prd.md"

    result = _inject_frontmatter(content, pipeline_id, model, domain)
    filepath = vault_paths.wiki_domain_dir(domain, "prds") / filename
    atomic_write(filepath, result)
    size = len(result.encode("utf-8"))
    logger.info("Written PRD: %s, size=%d bytes", filepath, size)
    return filepath


def write_epic(
    epic_data: dict,
    pipeline_id: str,
    model: str,
    slug: str,
    domain: str,
) -> Path:
    """Write epic to ``wiki/domains/<domain>/epics/<date>-<slug>-epic.md``."""
    clean_slug = slugify(slug, allow_unicode=True)
    today = date.today().isoformat()
    filename = f"{today}-{clean_slug}-epic.md"

    title = epic_data.get("title", "")
    goal = epic_data.get("goal", "")
    success_metrics = epic_data.get("success_metrics", [])
    body_markdown = epic_data.get("body_markdown", "")

    tasks_data = epic_data.get("_tasks_ref", [])
    total_tasks = len(tasks_data)
    total_story_points = sum(t.get("story_points", 0) for t in tasks_data)

    metrics_text = "\n".join(f"- {m}" for m in success_metrics)

    body = (
        f"# Epic: {title}\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Success Metrics\n{metrics_text}\n\n"
        f"{body_markdown}"
    )

    metadata = {
        "pipeline_id": pipeline_id,
        "domain": domain,
        "stage": "decomposer",
        "model": model,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "total_tasks": total_tasks,
        "total_story_points": total_story_points,
        "tags": ["pipeline", "epic"],
    }
    post = frontmatter.Post(body, **metadata)
    content = frontmatter.dumps(post)

    filepath = vault_paths.wiki_domain_dir(domain, "epics") / filename
    atomic_write(filepath, content)
    size = len(content.encode("utf-8"))
    logger.info("Written epic: %s, size=%d bytes", filepath, size)
    return filepath


def write_tasks(
    tasks_data: list,
    pipeline_id: str,
    model: str,
    slug: str,
    domain: str,
) -> list:
    """Write tasks to ``wiki/domains/<domain>/tasks/<date>-<slug>-task-NN.md``."""
    clean_slug = slugify(slug, allow_unicode=True)
    today = date.today().isoformat()
    tasks_dir = vault_paths.wiki_domain_dir(domain, "tasks")

    paths = []
    for idx, task in enumerate(tasks_data, start=1):
        task_id = task.get("id", f"TASK-{idx:02d}")
        title = task.get("title", "")
        task_type = task.get("type", "")
        story_points = task.get("story_points", 0)
        priority = task.get("priority", "medium")
        depends_on = task.get("depends_on", [])
        description_markdown = task.get("description_markdown", "")

        body = f"# {title}\n\n{description_markdown}"

        metadata = {
            "pipeline_id": pipeline_id,
            "domain": domain,
            "task_id": task_id,
            "type": task_type,
            "story_points": story_points,
            "priority": priority,
            "depends_on": depends_on,
            "tags": ["pipeline", "task"],
        }
        post = frontmatter.Post(body, **metadata)
        content = frontmatter.dumps(post)

        filename = f"{today}-{clean_slug}-task-{idx:02d}.md"
        filepath = tasks_dir / filename
        atomic_write(filepath, content)
        size = len(content.encode("utf-8"))
        logger.info("Written %s: %s, size=%d bytes", filename, filepath, size)
        paths.append(filepath)
    return paths


def save_state(state_dict: dict, slug: str, domain: str) -> Path:
    """Save pipeline state to ``wiki/domains/<domain>/ideas/<slug>_state.json``."""
    clean_slug = slugify(slug, allow_unicode=True)
    state_dir = vault_paths.wiki_domain_dir(domain, "ideas")
    filepath = state_dir / f"{clean_slug}_state.json"
    content = json.dumps(state_dict, indent=2, ensure_ascii=False)
    atomic_write(filepath, content)
    size = len(content.encode("utf-8"))
    logger.info("Written state: %s, size=%d bytes", filepath, size)
    return filepath


def load_state(slug: str, domain: str) -> dict | None:
    """Load pipeline state from ``wiki/domains/<domain>/ideas/<slug>_state.json``."""
    clean_slug = slugify(slug, allow_unicode=True)
    state_dir = vault_paths.wiki_domain_dir(domain, "ideas")
    filepath = state_dir / f"{clean_slug}_state.json"
    if not filepath.exists():
        logger.info("State file not found at %s, returning None", filepath)
        return None
    try:
        content = filepath.read_text(encoding="utf-8")
        state = json.loads(content)
        logger.info("Loaded state from %s", filepath)
        return state
    except Exception as exc:
        logger.error("Failed to load state from %s: %s", filepath, exc)
        return None
