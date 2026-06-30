import logging
import os
import signal
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from shared import vault_paths
from shared.frontmatter_utils import read_frontmatter

from .enricher import enrich
from .status_migrator import VALID_STATUSES

logger = logging.getLogger(__name__)

_SKIP_ENRICH_STATUSES = frozenset({"enriched"}) | VALID_STATUSES


class InboxHandler(FileSystemEventHandler):
    def __init__(self, vault_path: str):
        self.vault_path = vault_path

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        if path.suffix.lower() != ".md":
            return
        if path.stem.endswith(".tmp"):
            return

        logger.info(f"New file detected: {path.name}")
        time.sleep(1)

        try:
            metadata, _ = read_frontmatter(path)
            status = metadata.get("status", "Новая")
            if status in _SKIP_ENRICH_STATUSES:
                logger.info(f"File already {status}, skipping: {path.name}")
                return
        except Exception as e:
            logger.warning(f"Could not read frontmatter for {path.name}: {e}")

        logger.info(f"Auto-enriching: {path.name}")
        try:
            result = enrich(str(path), self.vault_path)
            logger.info(f"Auto-enrichment result for {path.name}: {result['status']}")
        except Exception as e:
            logger.error(f"Auto-enrichment failed for {path.name}: {e}")


class ClippingsHandler(FileSystemEventHandler):
    """Watch raw/inbound/clippings/ for new .md files and ingest them."""

    DEBOUNCE_SECONDS = 3

    def __init__(self):
        self._pending: dict[str, float] = {}

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md":
            return
        if path.stem.endswith(".tmp"):
            return
        self._schedule_ingest(path)

    def on_modified(self, event):
        """Handle file modifications -- Web Clipper may write content after create."""
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md":
            return
        if path.stem.endswith(".tmp"):
            return
        self._schedule_ingest(path)

    def _schedule_ingest(self, path: Path):
        now = time.time()
        first_seen = self._pending.get(str(path))

        if first_seen is None:
            self._pending[str(path)] = now
            logger.info("ClippingsHandler: new file detected, waiting for debounce: %s", path.name)
            return

        elapsed = now - first_seen
        if elapsed < self.DEBOUNCE_SECONDS:
            logger.debug("ClippingsHandler: debounce window, skipping: %s (%.1fs)", path.name, elapsed)
            return

        del self._pending[str(path)]
        logger.info("ClippingsHandler: debounce passed, ingesting: %s", path.name)
        self._do_ingest(path)

    def _do_ingest(self, path: Path):
        try:
            from .ingest import ingest_one
            result = ingest_one(path, vault_paths.vault_root())
            status = result.get("status", "error")
            if status == "ok":
                logger.info("ClippingsHandler: ingested %s -> %s", path.name, result.get("id"))
            elif status == "skip":
                logger.info("ClippingsHandler: skipped %s: %s", path.name, result.get("message"))
            else:
                logger.error("ClippingsHandler: error for %s: %s", path.name, result.get("message"))
        except Exception as e:
            logger.error("ClippingsHandler: unhandled error for %s: %s", path.name, e)


class DigestHandler(FileSystemEventHandler):
    """Watch wiki/ directories for .md changes and auto-generate digest to llm_wiki/."""

    DEBOUNCE_SECONDS = 5

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self._pending: dict[str, float] = {}

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md":
            return
        if path.stem.endswith(".tmp"):
            return
        self._schedule_digest(path)

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".md":
            return
        if path.stem.endswith(".tmp"):
            return
        self._schedule_digest(path)

    def _schedule_digest(self, path: Path):
        now = time.time()
        first_seen = self._pending.get(str(path))

        if first_seen is None:
            self._pending[str(path)] = now
            logger.info(f"DigestHandler: new file detected, waiting for debounce: {path.name}")
            return

        elapsed = now - first_seen
        if elapsed < self.DEBOUNCE_SECONDS:
            logger.debug(f"DigestHandler: debounce window, skipping: {path.name} ({elapsed:.1f}s)")
            return

        del self._pending[str(path)]
        logger.info(f"DigestHandler: debounce passed, generating: {path.name}")
        self._do_generate(path)

    def _should_process(self, path: Path) -> bool:
        if path.suffix.lower() != ".md":
            return False

        try:
            metadata, body = read_frontmatter(path)
        except Exception as e:
            logger.warning(f"DigestHandler: could not read frontmatter for {path.name}: {e}")
            return False

        status = metadata.get("status", "")
        if status == "draft":
            logger.debug(f"DigestHandler: draft status, skipping: {path.name}")
            return False

        from .digest.paths import wiki_to_llm_wiki
        from .digest.generator import _compute_body_hash

        vault_root = Path(self.vault_path)
        try:
            digest_path = wiki_to_llm_wiki(path, vault_root)
        except ValueError as e:
            logger.debug(f"DigestHandler: path not under wiki/, skipping: {path.name}: {e}")
            return False

        current_hash = _compute_body_hash(body)

        if digest_path.exists():
            try:
                digest_meta, _ = read_frontmatter(digest_path)
                existing_hash = digest_meta.get("body_hash", "")
                if existing_hash == current_hash:
                    logger.debug(f"DigestHandler: body unchanged, skipping: {path.name}")
                    return False
            except Exception as e:
                logger.warning(f"DigestHandler: could not read digest frontmatter for {path.name}: {e}")

        return True

    def _do_generate(self, path: Path):
        if not self._should_process(path):
            return
        try:
            from .digest.generator import generate_digest
            result = generate_digest(str(path), self.vault_path, force=False)
            logger.info(f"DigestHandler: digest generated for {path.name}, status={result.get('status')}")
        except Exception as e:
            logger.warning(f"DigestHandler: generation failed for {path.name}: {e}")


def start_watch(vault_path: str):
    logger.info(f"Starting watcher, vault_path={vault_path}")
    logger.info("Using polling observer (interval: 5s)")

    # Discover all domain idea directories to watch
    domains = vault_paths.all_domains()
    watch_dirs = []

    for domain in domains:
        ideas_dir = vault_paths.wiki_domain_dir(domain, "ideas")
        watch_dirs.append(ideas_dir)
        logger.info(f"Will watch domain ideas dir: {ideas_dir}")

    if not watch_dirs:
        logger.warning("No domain directories found. Watcher will start but has nothing to watch.")
        logger.info("Create domain directories under wiki/domains/<domain>/ideas/ to start watching.")

    handler = InboxHandler(vault_path)
    observer = PollingObserver(timeout=5)

    for watch_dir in watch_dirs:
        observer.schedule(handler, str(watch_dir), recursive=False)
        logger.info(f"Scheduled observer on: {watch_dir}")

    # Watch clippings directory
    clippings_dir = vault_paths.raw_clippings()
    clippings_handler = ClippingsHandler()
    observer.schedule(clippings_handler, str(clippings_dir), recursive=False)
    logger.info("Scheduled clippings observer on: %s", clippings_dir)

    # Watch wiki/ directories for digest generation (Layer 1')
    digest_enabled = os.getenv("DIGEST_ENABLED", "0") == "1"
    if digest_enabled:
        digest_handler = DigestHandler(vault_path)
        # Register on all wiki/ domain directories (all artifact types)
        for domain in domains:
            for art_type in vault_paths._VALID_ARTIFACT_TYPES:
                domain_type_dir = vault_paths.wiki_domain_dir(domain, art_type)
                observer.schedule(digest_handler, str(domain_type_dir), recursive=False)
                logger.info(f"DigestHandler: scheduled on domain dir: {domain_type_dir}")
        # Register on meetings/, daily-logs/, reports/ if they exist
        for extra_dir_name in ("meetings", "daily-logs", "reports"):
            extra_dir = vault_paths.VAULT_PATH / "wiki" / extra_dir_name
            if extra_dir.exists():
                observer.schedule(digest_handler, str(extra_dir), recursive=False)
                logger.info(f"DigestHandler: scheduled on: {extra_dir}")
        logger.info("DigestHandler: registered on all wiki/ directories")
    else:
        logger.info("DigestHandler: disabled (DIGEST_ENABLED != 1)")

    observer.start()
    logger.info(f"Watching {len(watch_dirs)} domain idea dirs + clippings for new .md files (Ctrl+C to stop)")

    stop = False

    def _signal_handler(signum, frame):
        nonlocal stop
        logger.info("Received stop signal, shutting down watcher")
        stop = True

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        while not stop:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        logger.info("Watcher stopped")
