import os
import logging
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

import json
import re
import subprocess

from .claude_client import process_idea, process_jira_ticket, process_daily
from .obsidian_writer import write_idea, write_jira_draft, write_daily
import tempfile
from pathlib import Path
from .stt import transcribe
from . import vault_paths
from .vault_paths import VAULT_PATH

logger = logging.getLogger(__name__)

ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID") or "0")


def _fallback_idea_data(raw_text: str) -> dict:
    """Build minimal idea dict when Claude API is unavailable."""
    title = raw_text[:50].strip()
    if len(raw_text) > 50 and " " in title:
        title = title[:title.rfind(" ")]
    return {
        "title": title or "Без LLM анализа",
        "domain": "general",
        "problem": raw_text,
        "solution": "",
        "usp": "",
        "metric": "",
        "tags": ["idea"],
    }


def _fallback_jira_content(raw_text: str) -> str:
    """Build minimal Markdown content for a jira draft when Claude API is unavailable."""
    today = date.today().isoformat()
    return (
        "---\n"
        f"title: Без LLM анализа\n"
        f"status: draft\n"
        f"domain: general\n"
        f"created: {today}\n"
        f"llm_processed: false\n"
        "---\n"
        "\n"
        "# Без LLM анализа\n"
        "\n"
        f"{raw_text}\n"
    )


def _is_allowed(update: Update) -> bool:
    """Принимаем сообщения только от владельца бота."""
    if ALLOWED_CHAT_ID == 0:
        # Режим первого запуска — выводим chat_id и блокируем
        return False
    return update.effective_chat.id == ALLOWED_CHAT_ID

def _run_enrichment(filepath):
    logger.info(f"Calling knowledge-engine enrich: {filepath}")
    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "enrich", str(filepath)],
            capture_output=True, text=True, timeout=30
        )
        logger.info(f"Enrichment exit code: {result.returncode}")
        if result.returncode != 0:
            logger.warning(f"Enrichment stderr: {result.stderr}")
        return result
    except subprocess.TimeoutExpired:
        logger.error("Enrichment timed out")
        return None
    except Exception as e:
        logger.error(f"Enrichment failed: {e}")
        return None


async def _send_idea_with_prompt(message, context, filepath, enrich_info=None):
    """Send idea confirmation with inline keyboard asking about pipeline."""
    text = f"✅ Идея сохранена:\n`{filepath.name}`"
    if enrich_info:
        text += f"\n{enrich_info}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Проработать", callback_data="pipeline"),
            InlineKeyboardButton("Просто зафиксировать", callback_data="skip_pipeline"),
        ]
    ])

    sent = await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    try:
        relative = str(filepath.relative_to(VAULT_PATH))
    except ValueError:
        relative = str(filepath)
    context.chat_data[f"pipeline_file:{sent.message_id}"] = relative
    logger.info("Idea saved with prompt: message_id=%s, filepath=%s", sent.message_id, filepath)


def _format_jira_sync_message(sync_result: dict) -> str:
    """Format Telegram reply text for daily Jira key sync results."""
    keys = sync_result.get("keys", [])
    if not keys:
        return ""

    imported = sync_result.get("imported", [])
    failed = sync_result.get("failed", [])
    missing = sync_result.get("missing", [])

    parts = [f"\U0001f4cb Задачи в протоколе: {', '.join(keys)}"]

    if not missing:
        parts[0] += " (все в vault)"
    elif imported:
        imported_strs = [
            f"{i['key']} → {i['domain']}/{i.get('artifact_type', 'tasks')}"
            for i in imported
        ]
        parts.append(f"⬇️ Импортировано из Jira: {', '.join(imported_strs)}")

    if failed:
        failed_strs = [f['key'] for f in failed]
        parts.append(f"⚠️ Не удалось импортировать: {', '.join(failed_strs)}")

    return "\n".join(parts)


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from the beginning of text."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def _split_message(text: str, limit: int = 4096) -> list[str]:
    """Split text into chunks respecting line boundaries."""
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if ALLOWED_CHAT_ID == 0:
        await update.message.reply_text(
            f"👋 Твой Chat ID: `{chat_id}`\n\n"
            f"Скопируй это число в `.env` как `ALLOWED_CHAT_ID={chat_id}` "
            f"и перезапусти контейнер.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "PM Bot готов. Команды:\n"
            "/idea — следующее сообщение → идея в Inbox\n"
            "/jira — следующее сообщение → черновик Jira-тикета\n"
            "/daily — следующее сообщение → дневной лог\n"
            "/jira_sync — синхронизировать задачи из Jira\n"
            "/jira_import <KEY> — импортировать задачу из Jira по ключу\n"
            "/pipeline — запустить проработку идеи в PRD + задачи\n"
            "/pipeline_file — запустить pipeline из файла в vault\n"
            "/pipeline_status — статус pipeline\n"
            "/pipeline_resume — перезапустить pipeline с этапа\n"
            "/domain list — список доменов\n"
            "/domain create <name> — создать домен\n"
            "/rebuild_index — обновить индексы доменов\n"
            "/ingest — обработать клиппинги из raw/inbound/clippings/\n"
            "/lint — проверить vault на проблемы\n"
            "/status — статус vault: домены, артефакты, здоровье\n\n"
            "Или просто напиши — по умолчанию идёт в Inbox."
        )

async def handle_idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    context.user_data["mode"] = "idea"
    await update.message.reply_text("Пиши идею 👇")

async def handle_jira(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    context.user_data["mode"] = "jira"
    await update.message.reply_text("Опиши задачу для Jira 👇")

async def handle_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    context.user_data["mode"] = "daily"
    await update.message.reply_text("Пиши дневную заметку 👇")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        chat_id = update.effective_chat.id
        await update.message.reply_text(f"Доступ закрыт. Твой chat_id: {chat_id}")
        return

    text = update.message.text
    mode = context.user_data.get("mode", "idea")
    context.user_data["mode"] = "idea"  # сброс после использования

    await update.message.reply_text("⏳ Обрабатываю...")

    try:
        if mode == "jira":
            try:
                result = process_jira_ticket(text)
            except Exception as llm_err:
                logger.warning("handle_text: Claude API failed, saving raw jira draft: %s", llm_err)
                result = _fallback_jira_content(text)
            filepath = write_jira_draft(result)
            msg = f"✅ Черновик Jira сохранён:\n`{filepath.name}`\n\n{result[:500]}..."
            try:
                await update.message.reply_text(msg, parse_mode="Markdown")
            except Exception:
                logger.warning("handle_text: Markdown parse failed for jira reply, sending plain text")
                await update.message.reply_text(f"✅ Черновик Jira сохранён:\n{filepath.name}\n\n{result[:500]}...")
        elif mode == "daily":
            result = process_daily(text)
            filepath = write_daily(result)

            jira_msg = ""
            try:
                from knowledge_engine.jira_key_sync import sync_daily_jira_keys, patch_daily_links
                sync_result = sync_daily_jira_keys(result, str(vault_paths.VAULT_PATH))
                jira_msg = _format_jira_sync_message(sync_result)
                patch_daily_links(str(filepath), sync_result.get("keys_map", {}))
            except Exception as e:
                logger.warning("handle_text: daily jira sync failed (non-fatal): %s", e)

            msg = f"✅ Daily log сохранён:\n`{filepath.name}`"
            if jira_msg:
                msg += f"\n{jira_msg}"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            try:
                idea_data = process_idea(text)
            except Exception as llm_err:
                logger.warning("handle_text: Claude API failed, saving raw idea: %s", llm_err)
                idea_data = _fallback_idea_data(text)

            filepath = write_idea(idea_data, text)

            enrich_result = _run_enrichment(filepath)
            enrich_info = None
            if enrich_result and enrich_result.returncode == 0:
                try:
                    data = json.loads(enrich_result.stdout)
                    links = data.get("links_found", 0)
                    enrich_info = f"Обогащено: {links} связей"
                except json.JSONDecodeError:
                    enrich_info = "(обогащение выполнено)"

            await _send_idea_with_prompt(update.message, context, filepath, enrich_info)
    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def handle_synthesize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("⏳ Запускаю синтез...")
    logger.info("Starting synthesis via knowledge-engine")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "synthesize"],
            capture_output=True, text=True, timeout=120
        )
        logger.info(f"Synthesis exit code: {result.returncode}")

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if data["status"] == "ok":
                    header = f"✅ Синтез завершён: {data['file']}\nИдей обработано: {data.get('count', '?')}"
                    await update.message.reply_text(header)
                    summary = data['summary'][:500]
                    if summary:
                        await update.message.reply_text(summary)
                else:
                    await update.message.reply_text(data.get("message", "Нет новых идей для синтеза"))
            except json.JSONDecodeError:
                await update.message.reply_text("✅ Синтез завершён")
        else:
            logger.error(f"Synthesis failed: {result.stderr}")
            await update.message.reply_text(f"❌ Ошибка синтеза: {result.stderr[:200]}")

    except subprocess.TimeoutExpired:
        logger.error("Synthesis timed out")
        await update.message.reply_text("❌ Синтез не завершился за 2 минуты")
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_fetch_meetings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("Проверяю почту на новые транскрибации...")
    logger.info("Manual fetch_meetings triggered via Telegram")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "fetch-meetings", "--notify"],
            capture_output=True, text=True, timeout=180
        )
        logger.info(f"fetch-meetings exit code: {result.returncode}")

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if data["newly_processed"] > 0:
                    details = "\n".join(
                        f"  {d['file']} ({d['type']})"
                        for d in data.get("details", [])
                    )
                    await update.message.reply_text(
                        f"Обработано протоколов: {data['newly_processed']}\n{details}"
                    )
                else:
                    await update.message.reply_text(
                        "Новых транскрибаций не найдено"
                    )
            except json.JSONDecodeError:
                await update.message.reply_text("Проверка завершена")
        else:
            logger.error(f"fetch-meetings failed: {result.stderr}")
            await update.message.reply_text(
                f"Ошибка: {result.stderr[:200]}"
            )

    except subprocess.TimeoutExpired:
        logger.error("fetch-meetings timed out")
        await update.message.reply_text("Не завершилось за 3 минуты")
    except Exception as e:
        logger.error(f"fetch-meetings error: {e}")
        await update.message.reply_text(f"Ошибка: {e}")


async def handle_jira_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("⏳ Синхронизирую с Jira...")
    logger.info("Manual jira_sync triggered via Telegram: chat_id=%s", update.effective_chat.id)

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-sync"],
            capture_output=True, text=True, timeout=120
        )
        logger.info("jira-sync exit code: %s", result.returncode)

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                new = data.get("new", 0)
                updated = data.get("updated", 0)
                closed = data.get("closed", 0)
                errors = data.get("errors", 0)

                msg = f"✅ Jira sync: {new} new, {updated} updated, {closed} closed"
                if errors > 0:
                    msg += f", {errors} errors"
                await update.message.reply_text(msg)
                logger.info("jira_sync completed: new=%d, updated=%d, closed=%d, errors=%d", new, updated, closed, errors)
            except json.JSONDecodeError:
                logger.error("jira_sync: failed to parse JSON from stdout")
                await update.message.reply_text("✅ Синхронизация завершена")
        else:
            # Try to parse error from JSON output
            error_msg = result.stderr[:200]
            try:
                data = json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except (json.JSONDecodeError, Exception):
                pass
            logger.error("jira_sync failed: %s", error_msg)
            await update.message.reply_text(f"❌ Ошибка: {error_msg}")

    except subprocess.TimeoutExpired:
        logger.error("jira_sync timed out")
        await update.message.reply_text("❌ Синхронизация не завершилась за 2 минуты")
    except Exception as e:
        logger.error("jira_sync error: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_jira_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    key = " ".join(context.args) if context.args else ""
    if not key:
        await update.message.reply_text("Укажи ключ задачи. Пример: /jira_import GO-153")
        return

    import re as _re
    if not _re.match(r'^[A-Z][A-Z0-9]+-\d+$', key):
        await update.message.reply_text("Неверный формат ключа. Пример: /jira_import GO-153")
        return

    await update.message.reply_text(f"⏳ Импортирую {key}...")
    logger.info("jira_import: key=%s, chat_id=%s", key, update.effective_chat.id)

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-import", key],
            capture_output=True, text=True, timeout=60
        )
        logger.info("jira_import exit code: %s", result.returncode)

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                domain = data.get("domain", "?")
                status = data.get("task_status", "?")
                action = data.get("action", "imported")
                title = data.get("title", "")
                title_short = title[:60] + "..." if len(title) > 60 else title
                msg = f"✅ {key} ({action})\n📁 {domain}\n📋 {status}"
                if title_short:
                    msg += f"\n📝 {title_short}"
                await update.message.reply_text(msg)
                logger.info("jira_import completed: key=%s domain=%s status=%s action=%s", key, domain, status, action)
            except json.JSONDecodeError:
                logger.error("jira_import: failed to parse JSON from stdout")
                await update.message.reply_text("✅ Импорт завершён")
        else:
            error_msg = result.stderr[:200]
            try:
                data = json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except (json.JSONDecodeError, Exception):
                pass
            logger.error("jira_import failed: %s", error_msg)
            await update.message.reply_text(f"❌ {error_msg}")

    except subprocess.TimeoutExpired:
        logger.error("jira_import timed out: key=%s", key)
        await update.message.reply_text("❌ Импорт не завершился за 60 секунд")
    except Exception as e:
        logger.error("jira_import error: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_jira_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /jira_create <filename> <project_key> command.

    Creates a Jira issue from a vault task file.
    Usage: /jira_create 2026-05-06-search-task-01.md GO
    """
    if not _is_allowed(update):
        return

    if not context.args or len(context.args) != 2:
        await update.message.reply_text(
            "Укажи имя файла и ключ проекта. Пример: /jira_create 2026-05-06-search-task-01.md GO"
        )
        return

    filename, project_key = context.args[0], context.args[1]

    if not filename.endswith(".md"):
        await update.message.reply_text("Имя файла должно оканчиваться на .md")
        return

    import re as _re
    if not _re.match(r'^[A-Z][A-Z0-9]+$', project_key):
        await update.message.reply_text(
            "Неверный формат ключа проекта. Пример: GO, SEARCH, PM"
        )
        return

    logger.info("jira_create: filename=%s, project_key=%s, chat_id=%s", filename, project_key, update.effective_chat.id)
    await update.message.reply_text("⏳ Creating task in Jira...")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-create",
             "--file", filename, "--project", project_key],
            capture_output=True, text=True, timeout=120
        )
        logger.info("jira_create exit code: %s", result.returncode)

        try:
            data = json.loads(result.stdout)
            status = data.get("status", "error")
            jira_key = data.get("jira_key", "")
            jira_url = data.get("jira_url", "")
            message = data.get("message", "")

            if status == "ok":
                msg = f"✅ Created {jira_key}: {message}\n🔗 {jira_url}"
                logger.info("jira_create completed: filename=%s project=%s jira_key=%s", filename, project_key, jira_key)
            elif status == "already_exists":
                msg = f"ℹ️ Already in Jira: {jira_key}\n🔗 {jira_url}"
                logger.info("jira_create already_exists: filename=%s jira_key=%s", filename, jira_key)
            elif status == "partial":
                msg = f"⚠️ {message}\n🔗 {jira_url}"
                logger.warning("jira_create partial: filename=%s message=%s", filename, message)
            else:
                msg = f"❌ Failed: {message}"
                logger.error("jira_create failed: filename=%s message=%s", filename, message)

            await update.message.reply_text(msg)

        except json.JSONDecodeError:
            error_output = result.stderr or result.stdout[:200]
            logger.error("jira_create: failed to parse JSON. output=%s", error_output)
            await update.message.reply_text(f"❌ Unexpected error: {error_output}")

    except subprocess.TimeoutExpired:
        logger.error("jira_create timed out: filename=%s project_key=%s", filename, project_key)
        await update.message.reply_text("❌ Operation timed out (120s)")
    except Exception as e:
        logger.error("jira_create error: %s", e)
        await update.message.reply_text(f"❌ Error: {e}")


MAX_VOICE_DURATION = 600


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        chat_id = update.effective_chat.id
        await update.message.reply_text(f"Доступ закрыт. Твой chat_id: {chat_id}")
        return

    voice = update.message.voice

    if voice.duration > MAX_VOICE_DURATION:
        logger.warning(f"Голосовое слишком длинное: {voice.duration}s (макс {MAX_VOICE_DURATION}s)")
        await update.message.reply_text(
            f"⏱ Голосовое слишком длинное ({voice.duration} сек, макс. {MAX_VOICE_DURATION // 60} минут). "
            "Попробуй разбить на части."
        )
        return

    mode = context.user_data.get("mode", "idea")
    context.user_data["mode"] = "idea"

    await update.message.reply_text("⏳ Транскрибирую...")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(tmp_path)
        logger.info(f"Голосовое скачано: {voice.duration}s, {voice.file_size} байт")

        text = transcribe(tmp_path)

        if not text:
            await update.message.reply_text("🎤 Не удалось распознать речь в голосовом сообщении.")
            return

    except Exception as e:
        logger.error(f"Ошибка транскрибации: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Не удалось распознать голосовое: {e}")
        return
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
                logger.info("Временный аудиофайл удалён")
            except OSError as e:
                logger.warning(f"Не удалось удалить временный аудиофайл: {e}")

    await update.message.reply_text(f"🎤 Распознано:\n{text}")

    try:
        if mode == "jira":
            try:
                result = process_jira_ticket(text)
            except Exception as llm_err:
                logger.warning("handle_voice: Claude API failed, saving raw jira draft: %s", llm_err)
                result = _fallback_jira_content(text)
            filepath = write_jira_draft(result)
            msg = f"✅ Черновик Jira сохранён:\n`{filepath.name}`\n\n{result[:500]}..."
            try:
                await update.message.reply_text(msg, parse_mode="Markdown")
            except Exception:
                logger.warning("handle_voice: Markdown parse failed for jira reply, sending plain text")
                await update.message.reply_text(f"✅ Черновик Jira сохранён:\n{filepath.name}\n\n{result[:500]}...")
        elif mode == "daily":
            result = process_daily(text)
            filepath = write_daily(result)

            jira_msg = ""
            try:
                from knowledge_engine.jira_key_sync import sync_daily_jira_keys, patch_daily_links
                sync_result = sync_daily_jira_keys(result, str(vault_paths.VAULT_PATH))
                jira_msg = _format_jira_sync_message(sync_result)
                patch_daily_links(str(filepath), sync_result.get("keys_map", {}))
            except Exception as e:
                logger.warning("handle_voice: daily jira sync failed (non-fatal): %s", e)

            msg = f"✅ Daily log сохранён:\n`{filepath.name}`"
            if jira_msg:
                msg += f"\n{jira_msg}"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            try:
                idea_data = process_idea(text)
            except Exception as llm_err:
                logger.warning("handle_voice: Claude API failed, saving raw idea: %s", llm_err)
                idea_data = _fallback_idea_data(text)

            filepath = write_idea(idea_data, text)

            enrich_result = _run_enrichment(filepath)
            enrich_info = None
            if enrich_result and enrich_result.returncode == 0:
                try:
                    data = json.loads(enrich_result.stdout)
                    links = data.get("links_found", 0)
                    enrich_info = f"Обогащено: {links} связей"
                except json.JSONDecodeError:
                    enrich_info = "(обогащение выполнено)"

            await _send_idea_with_prompt(update.message, context, filepath, enrich_info)
    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Напиши идею после /pipeline. Пример: /pipeline улучшить поиск по удобствам")
        return

    await update.message.reply_text("⏳ Запускаю pipeline...")
    logger.info("Pipeline requested: chat_id=%s, text_len=%d", update.effective_chat.id, len(text))

    try:
        from .pipeline_client import run_pipeline
        result = run_pipeline(
            text=text,
            notify_chat_id=str(update.effective_chat.id),
        )
        await update.message.reply_text(
            f"🚀 Pipeline запущен: {result.get('vault_dir', '')}\n"
            f"ID: `{result.get('pipeline_id', '')}`\n"
            f"Уведомление придёт по завершении.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Pipeline start failed: {e}")
        await update.message.reply_text(f"❌ Не удалось запустить pipeline: {e}")


async def handle_pipeline_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    file_path = " ".join(context.args) if context.args else ""
    if not file_path:
        await update.message.reply_text("Укажи путь к файлу. Пример: /pipeline_file wiki/domains/static-metadata/ideas/IDEA-0001-2026-04-20-idea.md")
        return

    await update.message.reply_text("⏳ Запускаю pipeline из файла...")
    logger.info("Pipeline from file requested: chat_id=%s, file=%s", update.effective_chat.id, file_path)

    try:
        from .pipeline_client import run_pipeline
        result = run_pipeline(
            file_path=file_path,
            notify_chat_id=str(update.effective_chat.id),
        )
        await update.message.reply_text(
            f"🚀 Pipeline запущен из файла\n"
            f"ID: `{result.get('pipeline_id', '')}`\n"
            f"Уведомление придёт по завершении.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Pipeline file start failed: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_pipeline_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    pipeline_id = context.args[0] if context.args else None
    logger.info("Pipeline status requested: pipeline_id=%s", pipeline_id)

    try:
        from .pipeline_client import get_status, list_pipelines

        if pipeline_id:
            data = get_status(pipeline_id)
            artifacts = ", ".join(data.get("artifacts", []))
            text = (
                f"Pipeline: `{data['pipeline_id']}`\n"
                f"Статус: {data['status']}\n"
                f"Артефакты: {artifacts or 'нет'}\n"
                f"Папка: {data.get('vault_dir', '')}"
            )
            if data.get("error"):
                text += f"\nОшибка: {data['error'][:200]}"
        else:
            data = list_pipelines(limit=5)
            runs = data.get("runs", [])
            if not runs:
                text = "Нет запущенных pipeline"
            else:
                lines = ["Последние pipeline:"]
                for r in runs:
                    lines.append(f"- `{r['pipeline_id'][:8]}` {r['slug']} [{r['status']}]")
                text = "\n".join(lines)

        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Pipeline status failed: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_pipeline_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Формат: /pipeline_resume <этап> <pipeline_id>\n"
            "Этапы: analyst, pm, decomposer\n"
            "Пример: /pipeline_resume pm abc123"
        )
        return

    stage = context.args[0]
    pipeline_id = context.args[1]

    if stage not in ("analyst", "pm", "decomposer"):
        await update.message.reply_text("Этап должен быть: analyst, pm или decomposer")
        return

    await update.message.reply_text(f"⏳ Перезапускаю pipeline с этапа {stage}...")
    logger.info("Pipeline resume: pipeline_id=%s, stage=%s", pipeline_id, stage)

    try:
        from .pipeline_client import resume_pipeline
        result = resume_pipeline(pipeline_id, stage)
        await update.message.reply_text(
            f"🔄 Pipeline перезапущен с этапа {stage}\n"
            f"ID: `{result.get('pipeline_id', '')}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Pipeline resume failed: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


def _pluralize_artifact(n: int) -> str:
    """Return correct Russian plural form for 'артефакт'."""
    if 11 <= n % 100 <= 19:
        return "артефактов"
    rem = n % 10
    if rem == 1:
        return "артефакт"
    if 2 <= rem <= 4:
        return "артефакта"
    return "артефактов"


async def handle_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    args = context.args or []

    if not args:
        logger.info("Domain command called with no subcommand: chat_id=%s", update.effective_chat.id)
        await update.message.reply_text(
            "Управление доменами:\n"
            "/domain list — список доменов\n"
            "/domain create <name> — создать домен"
        )
        return

    subcommand = args[0]

    if subcommand == "list":
        await update.message.reply_text("⏳ Получаю список доменов...")
        logger.info("Domain list requested: chat_id=%s", update.effective_chat.id)
        try:
            result = subprocess.run(
                ["python", "-m", "knowledge_engine", "domain", "list", "--format", "json"],
                capture_output=True, text=True, timeout=60
            )
            logger.info("Domain list exit code: %s", result.returncode)
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    domains = data.get("domains", [])
                    count = data.get("count", len(domains))
                    if count == 0:
                        await update.message.reply_text("📂 Доменов нет")
                    else:
                        lines = ["📂 Домены:\n"]
                        for d in domains:
                            total = d.get("total", 0)
                            lines.append(f"{d['name']} — {total} {_pluralize_artifact(total)}")
                        lines.append(f"\nВсего: {count} {'домен' if count == 1 else 'домена' if 2 <= count <= 4 else 'доменов'}")
                        await update.message.reply_text("\n".join(lines))
                        logger.info("Domain list returned %d domains", count)
                except json.JSONDecodeError:
                    logger.error("Domain list: failed to parse JSON from stdout")
                    await update.message.reply_text("❌ Не удалось разобрать ответ knowledge-engine")
            else:
                logger.error("Domain list failed: %s", result.stderr)
                await update.message.reply_text(f"❌ Ошибка: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.error("Domain list timed out")
            await update.message.reply_text("❌ Команда не завершилась за 60 секунд")
        except Exception as e:
            logger.error("Domain list error: %s", e)
            await update.message.reply_text(f"❌ Ошибка: {e}")

    elif subcommand == "create":
        if len(args) < 2:
            await update.message.reply_text("Укажи имя домена. Пример: /domain create my-domain")
            return
        name = args[1]
        await update.message.reply_text("⏳ Создаю домен...")
        logger.info("Domain create requested: name=%s, chat_id=%s", name, update.effective_chat.id)
        try:
            result = subprocess.run(
                ["python", "-m", "knowledge_engine", "domain", "create", name],
                capture_output=True, text=True, timeout=60
            )
            logger.info("Domain create exit code: %s", result.returncode)
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout)
                    if data.get("status") == "ok":
                        logger.info("Domain created successfully: name=%s", name)
                        await update.message.reply_text(f'✅ Домен "{name}" создан')
                    else:
                        error_msg = data.get("message", data.get("error", "неизвестная ошибка"))
                        logger.error("Domain create returned error: %s", error_msg)
                        await update.message.reply_text(f"❌ {error_msg}")
                except json.JSONDecodeError:
                    logger.error("Domain create: failed to parse JSON from stdout")
                    await update.message.reply_text("❌ Не удалось разобрать ответ knowledge-engine")
            else:
                try:
                    data = json.loads(result.stdout)
                    error_msg = data.get("message", data.get("error", result.stderr[:200]))
                    logger.error("Domain create failed: %s", error_msg)
                    await update.message.reply_text(f"❌ {error_msg}")
                except (json.JSONDecodeError, Exception):
                    logger.error("Domain create failed: %s", result.stderr)
                    await update.message.reply_text(f"❌ {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.error("Domain create timed out: name=%s", name)
            await update.message.reply_text("❌ Команда не завершилась за 60 секунд")
        except Exception as e:
            logger.error("Domain create error: %s", e)
            await update.message.reply_text(f"❌ Ошибка: {e}")

    else:
        logger.info("Domain command: unknown subcommand=%s", subcommand)
        await update.message.reply_text(
            "Управление доменами:\n"
            "/domain list — список доменов\n"
            "/domain create <name> — создать домен"
        )


async def handle_lint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    logger.info("handle_lint: user=%s", update.effective_user.id)
    await update.message.reply_text("🔍 Запускаю проверку vault...")

    try:
        proc = subprocess.run(
            ["python", "-m", "knowledge_engine", "lint"],
            capture_output=True, text=True, timeout=60
        )
        logger.info("handle_lint: process returned code=%d", proc.returncode)

        if proc.returncode != 0:
            logger.error("handle_lint: stderr=%s", proc.stderr)
            await update.message.reply_text(f"❌ Ошибка линтера:\n{proc.stderr[:500]}")
            return

        result = json.loads(proc.stdout)
        summary = result["summary"]

        lines = ["📋 *Vault Health Report*\n"]

        if summary["total_issues"] == 0:
            lines.append("✅ Проблем не найдено!")
        else:
            lines.append(f"⚠️ Найдено проблем: *{summary['total_issues']}*\n")

            if summary["broken_links_count"] > 0:
                lines.append(f"🔗 Битые ссылки: {summary['broken_links_count']}")
                for item in result["broken_links"][:5]:
                    lines.append(f"  • `{item['file']}` L{item['line']}: [[{item['link']}]]")
                if summary["broken_links_count"] > 5:
                    lines.append(f"  _...и ещё {summary['broken_links_count'] - 5}_")

            if summary["orphan_pages_count"] > 0:
                lines.append(f"\n👻 Сиротские страницы: {summary['orphan_pages_count']}")
                for item in result["orphan_pages"][:5]:
                    lines.append(f"  • `{item['file']}` ({item['domain']})")
                if summary["orphan_pages_count"] > 5:
                    lines.append(f"  _...и ещё {summary['orphan_pages_count'] - 5}_")

            if summary["stale_drafts_count"] > 0:
                lines.append(f"\n📝 Устаревшие черновики (>30 дней): {summary['stale_drafts_count']}")
                for item in result["stale_drafts"][:5]:
                    lines.append(f"  • `{item['file']}` — {item['days_old']}д ({item['status']})")
                if summary["stale_drafts_count"] > 5:
                    lines.append(f"  _...и ещё {summary['stale_drafts_count'] - 5}_")

            if summary["unsorted_misc_count"] > 0:
                lines.append(f"\n📁 Несортированные в misc/ (>7 дней): {summary['unsorted_misc_count']}")
                for item in result["unsorted_misc"][:5]:
                    lines.append(f"  • `{item['file']}` — {item['days_old']}д")
                if summary["unsorted_misc_count"] > 5:
                    lines.append(f"  _...и ещё {summary['unsorted_misc_count'] - 5}_")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        logger.info("handle_lint: report sent, total_issues=%d", summary["total_issues"])

    except subprocess.TimeoutExpired:
        logger.error("handle_lint: timeout")
        await update.message.reply_text("❌ Таймаут проверки vault (60с)")
    except Exception as e:
        logger.error("handle_lint: error=%s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    logger.info("handle_status: user=%s", update.effective_user.id)
    await update.message.reply_text("📊 Собираю статус vault...")

    try:
        proc = subprocess.run(
            ["python", "-m", "knowledge_engine", "status"],
            capture_output=True, text=True, timeout=60
        )
        logger.info("handle_status: process returned code=%d", proc.returncode)

        if proc.returncode != 0:
            logger.error("handle_status: stderr=%s", proc.stderr)
            await update.message.reply_text(f"❌ Ошибка:\n{proc.stderr[:500]}")
            return

        result = json.loads(proc.stdout)

        lines = ["📊 *Vault Status*\n"]
        lines.append(f"🏷️ Доменов: *{result['domains_count']}*")
        lines.append(f"📄 Артефактов: *{result['total_artifacts']}*\n")

        if result["domains"]:
            lines.append("*Домены:*")
            for d in result["domains"]:
                parts = []
                if d.get("ideas", 0): parts.append(f"{d['ideas']} ideas")
                if d.get("prds", 0): parts.append(f"{d['prds']} prds")
                if d.get("epics", 0): parts.append(f"{d['epics']} epics")
                if d.get("tasks", 0): parts.append(f"{d['tasks']} tasks")
                if d.get("bugs", 0): parts.append(f"{d['bugs']} bugs")
                detail = ", ".join(parts) if parts else "пусто"
                lines.append(f"  • *{d['name']}*: {detail}")

        if result.get("raw_counts"):
            lines.append("\n*Raw/inbound:*")
            for folder, count in sorted(result["raw_counts"].items()):
                if count > 0:
                    lines.append(f"  • {folder}: {count}")

        health = result.get("health", {})
        total_issues = health.get("total_issues", 0)
        if total_issues > 0:
            lines.append(f"\n⚠️ Проблем: *{total_issues}* (используй /lint для деталей)")
        else:
            lines.append("\n✅ Проблем не найдено")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        logger.info("handle_status: report sent, domains=%d, artifacts=%d",
                    result["domains_count"], result["total_artifacts"])

    except subprocess.TimeoutExpired:
        logger.error("handle_status: timeout")
        await update.message.reply_text("❌ Таймаут сбора статуса (60с)")
    except Exception as e:
        logger.error("handle_status: error=%s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_rebuild_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    args = context.args or []
    domain = args[0] if args else None

    if domain:
        await update.message.reply_text("⏳ Обновляю индексы домена...")
        logger.info("Rebuild index requested for domain=%s, chat_id=%s", domain, update.effective_chat.id)
        cmd = ["python", "-m", "knowledge_engine", "rebuild-index", domain]
    else:
        await update.message.reply_text("⏳ Обновляю индексы всех доменов...")
        logger.info("Rebuild index requested for all domains: chat_id=%s", update.effective_chat.id)
        cmd = ["python", "-m", "knowledge_engine", "rebuild-index"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60
        )
        logger.info("Rebuild index exit code: %s", result.returncode)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                total = data.get("total_indices", 0)
                if domain:
                    logger.info("Rebuild index done for domain=%s, total=%s", domain, total)
                    await update.message.reply_text(
                        f'✅ Индексы домена "{domain}" обновлены: {total} индексов'
                    )
                else:
                    logger.info("Rebuild index done for all domains, total=%s", total)
                    await update.message.reply_text(
                        f"✅ Индексы обновлены: {total} индексов"
                    )
            except json.JSONDecodeError:
                logger.error("Rebuild index: failed to parse JSON from stdout")
                await update.message.reply_text("✅ Индексы обновлены")
        else:
            logger.error("Rebuild index failed: %s", result.stderr)
            await update.message.reply_text(f"❌ Ошибка: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        logger.error("Rebuild index timed out: domain=%s", domain)
        await update.message.reply_text("❌ Команда не завершилась за 60 секунд")
    except Exception as e:
        logger.error("Rebuild index error: %s", e)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def _handle_pipeline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # acknowledge the callback

    msg_id = query.message.message_id
    chat_id = query.message.chat_id

    if query.data == "pipeline":
        file_path = context.chat_data.pop(f"pipeline_file:{msg_id}", None)
        if not file_path:
            await query.message.reply_text("⚠️ Не удалось найти файл идеи. Попробуй /pipeline_file")
            # Remove keyboard
            await query.edit_message_reply_markup(reply_markup=None)
            return

        logger.info("Pipeline via inline: chat_id=%s, file=%s", chat_id, file_path)

        try:
            from .pipeline_client import run_pipeline
            result = run_pipeline(
                file_path=file_path,
                notify_chat_id=str(chat_id),
            )
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"🚀 Pipeline запущен\n"
                f"ID: `{result.get('pipeline_id', '')}`\n"
                f"Уведомлю по завершении.",
                parse_mode="Markdown"
            )
            logger.info("Pipeline started via inline: pipeline_id=%s, file=%s",
                        result.get('pipeline_id'), file_path)
        except Exception as e:
            logger.error("Pipeline inline start failed: %s", e)
            await query.edit_message_reply_markup(reply_markup=None)
            error_msg = str(e)
            if "409" in error_msg or "already running" in error_msg.lower():
                await query.message.reply_text("⚠️ Другой pipeline уже выполняется. Попробуй позже.")
            else:
                await query.message.reply_text(f"❌ Не удалось запустить pipeline: {e}")

    elif query.data == "skip_pipeline":
        logger.info("Pipeline skipped via inline: chat_id=%s, msg_id=%s", chat_id, msg_id)
        context.chat_data.pop(f"pipeline_file:{msg_id}", None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("👌 Ок, идея сохранена.")


async def handle_test_enrichment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger enrichment reminder check (dev/test only)."""
    logger.info("/test_enrichment command received from chat_id=%s", update.effective_chat.id)
    if not _is_allowed(update):
        logger.warning("/test_enrichment: unauthorized access from chat_id=%s", update.effective_chat.id)
        return

    await update.message.reply_text("Запускаю проверку enrichment...")
    logger.info("/test_enrichment: starting enrichment check")

    try:
        from .enrichment_reminder import run_enrichment_check
        await run_enrichment_check(context.bot, update.effective_chat.id)
        await update.message.reply_text("Enrichment check завершён. Проверь сообщения выше.")
        logger.info("/test_enrichment: completed successfully")
    except Exception as e:
        logger.error("/test_enrichment: failed: %s", e, exc_info=True)
        await update.message.reply_text(f"Ошибка: {e}")


async def handle_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /progress [DD.MM.YYYY] — send daily dev report from vault."""
    if not _is_allowed(update):
        return

    from datetime import datetime as _dt

    reports_dir = vault_paths.VAULT_PATH / "wiki" / "reports"
    suffix = "-Daily_Dev_Report.md"

    arg = " ".join(context.args).strip() if context.args else ""
    logger.info("handle_progress: arg='%s', chat_id=%s", arg, update.effective_chat.id)

    if arg:
        try:
            parsed = _dt.strptime(arg, "%d.%m.%Y")
            date_prefix = parsed.strftime("%Y.%m.%d")
            display_date = arg
        except ValueError:
            await update.message.reply_text(
                "Формат даты: DD.MM.YYYY. Пример: /progress 29.05.2026"
            )
            return

        target = reports_dir / f"{date_prefix}{suffix}"
        if not target.exists():
            latest = _find_latest_report(reports_dir, suffix)
            if latest:
                latest_date = latest.name.split("-Daily_Dev_Report")[0]
                parts = latest_date.split(".")
                if len(parts) == 3:
                    latest_display = f"{parts[2]}.{parts[1]}.{parts[0]}"
                else:
                    latest_display = latest_date
                await update.message.reply_text(
                    f"❌ Отчёт за {display_date} не найден. "
                    f"Последний доступный: {latest_display}"
                )
            else:
                await update.message.reply_text("❌ Отчёты не найдены в wiki/reports/")
            return
    else:
        target_file = _find_latest_report(reports_dir, suffix)
        if not target_file:
            await update.message.reply_text("❌ Отчёты не найдены в wiki/reports/")
            return
        target = target_file
        date_prefix = target.name.split("-Daily_Dev_Report")[0]
        parts = date_prefix.split(".")
        if len(parts) == 3:
            display_date = f"{parts[2]}.{parts[1]}.{parts[0]}"
        else:
            display_date = date_prefix

    content = target.read_text(encoding="utf-8")
    logger.info("handle_progress: read %s, len=%d", target.name, len(content))

    body = _strip_frontmatter(content)

    summary = _extract_report_summary(body)
    caption = f"📊 Отчёт за {display_date}"
    if summary:
        caption += f"\n\n{re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', summary)}"
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    await update.message.reply_document(
        document=open(str(target), "rb"),
        filename=target.name,
        caption=caption,
        parse_mode="HTML",
    )
    logger.info("handle_progress: sent file %s for %s", target.name, display_date)


def _extract_report_summary(body: str) -> str:
    """Extract risks/blockers section from report for Telegram caption."""
    lines = body.split("\n")
    summary_lines = []
    capture = False
    for line in lines:
        if line.strip().startswith("> **Риск") or line.strip().startswith("> 🔴") or line.strip().startswith("> 🟡"):
            capture = True
        if capture:
            if line.startswith("> "):
                summary_lines.append(line[2:])
            elif line.strip() == ">":
                summary_lines.append("")
            elif summary_lines and not line.strip():
                break
            else:
                break
    return "\n".join(summary_lines).strip()


def _find_latest_report(reports_dir, suffix):
    """Find the most recent *-Daily_Dev_Report.md file."""
    if not reports_dir.exists():
        return None
    candidates = sorted(
        [f for f in reports_dir.iterdir() if f.name.endswith(suffix)],
        key=lambda f: f.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


async def handle_ingest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text("Обрабатываю клиппинги...")
    logger.info("handle_ingest: triggered, chat_id=%s", update.effective_chat.id)

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "ingest-clippings", "--notify"],
            capture_output=True, text=True, timeout=120
        )
        logger.info("handle_ingest: exit code=%s", result.returncode)

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                processed = data.get("processed", 0)
                skipped = data.get("skipped", 0)
                errors = data.get("errors", 0)
                msg = f"Ingest: {processed} обработано, {skipped} пропущено, {errors} ошибок"
                logger.info("handle_ingest: success — %s", msg)
                await update.message.reply_text(msg)
            except json.JSONDecodeError:
                logger.warning("handle_ingest: could not parse JSON output")
                await update.message.reply_text("Ingest завершен")
        else:
            error_msg = result.stderr[:200] if result.stderr else "unknown error"
            try:
                data = json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except (json.JSONDecodeError, Exception):
                pass
            logger.error("handle_ingest: failed — %s", error_msg)
            await update.message.reply_text(f"Ошибка: {error_msg}")

    except subprocess.TimeoutExpired:
        logger.error("handle_ingest: timeout after 120s")
        await update.message.reply_text("Ingest не завершился за 2 минуты")
    except Exception as e:
        logger.error("handle_ingest: unhandled error: %s", e)
        await update.message.reply_text(f"Ошибка: {e}")


def get_handlers():
    return [
        CommandHandler("start", start),
        CommandHandler("idea", handle_idea),
        CommandHandler("jira", handle_jira),
        CommandHandler("daily", handle_daily),
        CommandHandler("synthesize", handle_synthesize),
        CommandHandler("fetch_meetings", handle_fetch_meetings),
        CommandHandler("jira_sync", handle_jira_sync),
        CommandHandler("jira_import", handle_jira_import),
        CommandHandler("jira_create", handle_jira_create),
        CommandHandler("pipeline", handle_pipeline),
        CommandHandler("pipeline_file", handle_pipeline_file),
        CommandHandler("pipeline_status", handle_pipeline_status),
        CommandHandler("pipeline_resume", handle_pipeline_resume),
        CommandHandler("domain", handle_domain),
        CommandHandler("rebuild_index", handle_rebuild_index),
        CommandHandler("lint", handle_lint),
        CommandHandler("status", handle_status),
        CommandHandler("ingest", handle_ingest),
        CommandHandler("test_enrichment", handle_test_enrichment),
        CommandHandler("progress", handle_progress),
        CallbackQueryHandler(_handle_pipeline_callback),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        MessageHandler(filters.VOICE, handle_voice),
    ]
