import logging
import signal
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from . import vault_paths
from .enricher import enrich
from .frontmatter_utils import read_frontmatter

logger = logging.getLogger(__name__)


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
            status = metadata.get("status", "inbox")
            if status in ("enriched", "processed"):
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
