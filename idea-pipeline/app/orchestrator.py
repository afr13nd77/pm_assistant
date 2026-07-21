import asyncio
import json
import logging
import time
from datetime import date
from pathlib import Path

from idea_pipeline import vault_writer
from idea_pipeline.agents.analyst import AnalystAgent
from idea_pipeline.agents.decomposer import DecomposerAgent
from idea_pipeline.agents.pm_agent import PMAgent
from idea_pipeline.claude_client import PipelineClaudeClient
from idea_pipeline.config import PipelineConfig
from idea_pipeline.state import PipelineStage, PipelineStore

from shared import vault_paths

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        config: PipelineConfig,
        claude_client: PipelineClaudeClient,
        store: PipelineStore,
        vault_path: Path,
    ) -> None:
        self.config = config
        self.client = claude_client
        self.store = store
        self.vault_path = vault_path
        self._lock = asyncio.Lock()
        self._running_pipeline_id: str | None = None

        self.analyst = AnalystAgent(config.agents["analyst"], claude_client)
        self.pm_agent = PMAgent(config.agents["pm"], claude_client)
        self.decomposer = DecomposerAgent(config.agents["decomposer"], claude_client)

        logger.info(
            "PipelineOrchestrator initialized: vault_path=%s, agents=%s",
            vault_path,
            list(config.agents.keys()),
        )

    @property
    def is_running(self) -> bool:
        return self._running_pipeline_id is not None

    @property
    def running_pipeline_id(self) -> str | None:
        return self._running_pipeline_id

    async def run_pipeline(
        self,
        pipeline_id: str,
        input_text: str,
        start_from: str = "analyst",
        notify_chat_id: str | None = None,
    ) -> None:
        """
        Main pipeline execution. Runs in background (called from FastAPI BackgroundTasks).
        Uses asyncio.to_thread for CPU-bound Claude API calls.
        """
        async with self._lock:
            if self._running_pipeline_id is not None:
                raise RuntimeError(
                    f"Pipeline {self._running_pipeline_id} is already running"
                )
            self._running_pipeline_id = pipeline_id

        logger.info(
            "Pipeline %s started: start_from=%s, input_len=%d",
            pipeline_id,
            start_from,
            len(input_text),
        )

        pipeline_start = time.monotonic()
        run = self.store.get(pipeline_id)
        domain = run.domain
        slug = run.slug
        today = date.today().isoformat()

        # --- Langfuse trace ---
        from shared.langfuse_client import get_langfuse

        lf = get_langfuse()
        trace = None
        if lf:
            try:
                trace = lf.trace(
                    name="idea_pipeline",
                    metadata={
                        "pipeline_id": pipeline_id,
                        "domain": domain,
                        "slug": slug,
                    },
                    tags=["pipeline"],
                )
                logger.info(
                    "Pipeline %s: Langfuse trace created", pipeline_id
                )
            except Exception as exc:
                logger.warning(
                    "run_pipeline: failed to create Langfuse trace: %s", exc
                )

        # analysis_text and prd_text flow between stages; set to None so each
        # stage can assert they were populated by the preceding one.
        analysis_text: str | None = None
        prd_text: str | None = None

        try:
            # --- Stage 1: Analyst ---
            if start_from == "analyst":
                self.store.update_stage(pipeline_id, PipelineStage.ANALYST_IN_PROGRESS)
                self._save_state(pipeline_id, domain, slug)

                vault_context = self._get_vault_context(input_text)

                analyst_span = None
                if trace:
                    try:
                        analyst_span = trace.span(name="analyst")
                    except Exception:
                        pass

                analysis_text = await asyncio.to_thread(
                    self.analyst.run, input_text, vault_context,
                    _langfuse_parent=analyst_span,
                )

                if analyst_span:
                    try:
                        analyst_span.end()
                    except Exception:
                        pass

                vault_writer.write_analysis(
                    analysis_text, pipeline_id,
                    self.config.agents["analyst"].model,
                    slug, domain,
                )
                self.store.add_artifact(pipeline_id, f"{today}-{slug}-analysis.md")
                self.store.update_stage(pipeline_id, PipelineStage.ANALYST_DONE)
                self._save_state(pipeline_id, domain, slug)

            # --- Stage 2: PM ---
            stages_after_analyst = ("analyst", "pm")
            if start_from in stages_after_analyst:
                self.store.update_stage(pipeline_id, PipelineStage.PM_IN_PROGRESS)
                self._save_state(pipeline_id, domain, slug)

                if start_from == "pm":
                    analysis_dir = vault_paths.wiki_domain_dir(domain, "ideas")
                    analysis_path = analysis_dir / f"{today}-{slug}-analysis.md"
                    analysis_text = analysis_path.read_text(encoding="utf-8")
                    logger.info(
                        "Pipeline %s: loaded analysis from %s, chars=%d",
                        pipeline_id,
                        analysis_path,
                        len(analysis_text),
                    )

                pm_span = None
                if trace:
                    try:
                        pm_span = trace.span(name="pm")
                    except Exception:
                        pass

                prd_text = await asyncio.to_thread(
                    self.pm_agent.run, analysis_text,
                    _langfuse_parent=pm_span,
                )

                if pm_span:
                    try:
                        pm_span.end()
                    except Exception:
                        pass

                vault_writer.write_prd(
                    prd_text, pipeline_id,
                    self.config.agents["pm"].model,
                    slug, domain,
                )
                self.store.add_artifact(pipeline_id, f"{today}-{slug}-prd.md")
                self.store.update_stage(pipeline_id, PipelineStage.PM_DONE)
                self._save_state(pipeline_id, domain, slug)

            # --- Stage 3: Decomposer ---
            stages_after_pm = ("analyst", "pm", "decomposer")
            if start_from in stages_after_pm:
                self.store.update_stage(
                    pipeline_id, PipelineStage.DECOMPOSER_IN_PROGRESS
                )
                self._save_state(pipeline_id, domain, slug)

                if start_from == "decomposer":
                    prd_dir = vault_paths.wiki_domain_dir(domain, "prds")
                    prd_path = prd_dir / f"{today}-{slug}-prd.md"
                    prd_text = prd_path.read_text(encoding="utf-8")
                    logger.info(
                        "Pipeline %s: loaded PRD from %s, chars=%d",
                        pipeline_id,
                        prd_path,
                        len(prd_text),
                    )

                decomposer_span = None
                if trace:
                    try:
                        decomposer_span = trace.span(name="decomposer")
                    except Exception:
                        pass

                decomposer_output = await asyncio.to_thread(
                    self.decomposer.run, prd_text,
                    _langfuse_parent=decomposer_span,
                )

                if decomposer_span:
                    try:
                        decomposer_span.end()
                    except Exception:
                        pass

                parsed = json.loads(decomposer_output)
                epic_data = parsed.get("epic", {})
                tasks_data = parsed.get("tasks", [])

                # vault_writer.write_epic uses _tasks_ref to compute total_tasks
                # and total_story_points for epic frontmatter without re-parsing.
                epic_data["_tasks_ref"] = tasks_data

                vault_writer.write_epic(
                    epic_data, pipeline_id,
                    self.config.agents["decomposer"].model,
                    slug, domain,
                )
                self.store.add_artifact(pipeline_id, f"{today}-{slug}-epic.md")

                task_paths = vault_writer.write_tasks(
                    tasks_data, pipeline_id,
                    self.config.agents["decomposer"].model,
                    slug, domain,
                )
                for tp in task_paths:
                    self.store.add_artifact(pipeline_id, tp.name)

                self.store.update_stage(pipeline_id, PipelineStage.COMPLETED)
                self._save_state(pipeline_id, domain, slug)

            elapsed = time.monotonic() - pipeline_start
            logger.info(
                "Pipeline %s completed in %.1fs, artifacts=%d",
                pipeline_id,
                elapsed,
                len(self.store.get(pipeline_id).artifacts),
            )

            self._send_notification(pipeline_id, notify_chat_id)

        except Exception as exc:
            elapsed = time.monotonic() - pipeline_start
            logger.error(
                "Pipeline %s failed at %.1fs: %s",
                pipeline_id,
                elapsed,
                exc,
                exc_info=True,
            )
            run = self.store.get(pipeline_id)
            failed_stage = run.stage.value.replace("_in_progress", "")
            self.store.set_error(pipeline_id, str(exc), failed_stage)
            self._save_state(pipeline_id, domain, slug)

            self._send_notification(pipeline_id, notify_chat_id, failed=True)

        finally:
            self._running_pipeline_id = None
            logger.info("Pipeline %s: lock released", pipeline_id)

    def _get_vault_context(self, idea_text: str) -> dict | None:
        """Try to get vault context using knowledge-engine modules."""
        try:
            from knowledge_engine.matcher import find_links
            from knowledge_engine.vault_index import build_index

            index = build_index(str(self.vault_path))
            links = find_links(idea_text, [], index)
            max_entries = self.config.vault_context_max_entries

            if links:
                vault_entries = [
                    {
                        "path": entry.path,
                        "title": entry.title,
                        "snippet": snippet,
                    }
                    for entry, _score, snippet in links[:max_entries]
                ]
                logger.info(
                    "Vault context: found %d related entries", len(vault_entries)
                )
                return {"vault_entries": vault_entries}

            logger.info("Vault context: no related entries found")
            return None

        except ImportError:
            logger.warning("knowledge_engine not available, skipping vault context")
            return None
        except Exception as exc:
            logger.warning(
                "Vault context retrieval failed, continuing without: %s", exc
            )
            return None

    def _save_state(self, pipeline_id: str, domain: str, slug: str) -> None:
        """Persist current in-memory state to the domain ideas directory."""
        try:
            run = self.store.get(pipeline_id)
            vault_writer.save_state(run.to_dict(), slug, domain)
        except Exception as exc:
            logger.error("Failed to save state file for pipeline %s: %s", pipeline_id, exc)

    def _send_notification(
        self,
        pipeline_id: str,
        chat_id: str | None,
        failed: bool = False,
    ) -> None:
        """Send Telegram notification about pipeline completion or failure."""
        if not self.config.notification_enabled:
            logger.info(
                "Pipeline %s: notifications disabled, skipping", pipeline_id
            )
            return
        if failed and not self.config.notify_on_failure:
            logger.info(
                "Pipeline %s: notify_on_failure=False, skipping failure notification",
                pipeline_id,
            )
            return
        if not failed and not self.config.notify_on_complete:
            logger.info(
                "Pipeline %s: notify_on_complete=False, skipping completion notification",
                pipeline_id,
            )
            return

        run = self.store.get(pipeline_id)
        if not chat_id:
            logger.info(
                "Pipeline %s: no chat_id provided, skipping notification", pipeline_id
            )
            return

        try:
            from knowledge_engine.notifier import send_telegram

            if failed:
                text = (
                    f"Pipeline остановлен\n"
                    f"Этап: {run.failed_stage}\n"
                    f"Ошибка: {run.error[:200] if run.error else 'unknown'}"
                )
            else:
                artifacts_list = ", ".join(run.artifacts)
                text = (
                    f"Pipeline завершён: {run.slug}\n"
                    f"Артефакты ({len(run.artifacts)}): {artifacts_list}\n"
                    f"Домен: {run.domain}"
                )

            send_telegram(message=text, chat_id=chat_id)
            logger.info(
                "Pipeline %s: notification sent to chat_id=%s, failed=%s",
                pipeline_id,
                chat_id,
                failed,
            )
        except ImportError:
            logger.warning(
                "knowledge_engine.notifier not available, skipping notification"
            )
        except Exception as exc:
            logger.error(
                "Pipeline %s: failed to send notification: %s", pipeline_id, exc
            )
