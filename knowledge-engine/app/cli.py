import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        prog="knowledge_engine",
        description="Knowledge Engine — enrichment and synthesis for Obsidian vault"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enrich_parser = subparsers.add_parser("enrich", help="Enrich a single idea file with vault links")
    enrich_parser.add_argument("filepath", help="Path to the .md file to enrich")
    enrich_parser.add_argument("--vault", default=None, help="Vault root path (default: /vault or $VAULT_PATH)")
    enrich_parser.add_argument("--dry-run", action="store_true", help="Print what would be added, do not modify file")

    synth_parser = subparsers.add_parser("synthesize", help="Synthesize all pending ideas into a summary")
    synth_parser.add_argument("--vault", default=None, help="Vault root path")
    synth_parser.add_argument("--notify", action="store_true", help="Send Telegram notification on completion")
    synth_parser.add_argument("--min-ideas", type=int, default=1, help="Minimum ideas to trigger synthesis (default: 1)")
    synth_parser.add_argument("--dry-run", action="store_true", help="Print plan without writing files")

    watch_parser = subparsers.add_parser("watch", help="Start watchdog daemon on wiki/domains/*/ideas/")
    watch_parser.add_argument("--vault", default=None, help="Vault root path")

    index_parser = subparsers.add_parser("index", help="Build and print vault index (debug)")
    index_parser.add_argument("--vault", default=None, help="Vault root path")
    index_parser.add_argument("--format", choices=["json", "table"], default="json", help="Output format")

    fetch_parser = subparsers.add_parser(
        "fetch-meetings",
        help="Fetch meeting transcripts from IMAP and create protocols"
    )
    fetch_parser.add_argument("--vault", default=None, help="Vault root path")
    fetch_parser.add_argument("--notify", action="store_true", help="Send Telegram notification per protocol")
    fetch_parser.add_argument("--dry-run", action="store_true", help="List new emails without processing")

    domain_parser = subparsers.add_parser("domain", help="Manage vault domains")
    domain_parser.add_argument("--vault", default=None, help="Vault root path")
    domain_subparsers = domain_parser.add_subparsers(dest="domain_command", required=True)

    domain_create_parser = domain_subparsers.add_parser("create", help="Create a new domain with full scaffolding")
    domain_create_parser.add_argument("name", help="Domain name (lowercase alphanumeric, hyphens allowed)")
    domain_create_parser.add_argument("--display-name", default=None, dest="display_name",
                                      help="Human-readable display name (default: same as slug)")
    domain_create_parser.add_argument("--color", default=None,
                                      help="Domain color as hex code (default: #607D8B)")
    domain_create_parser.add_argument("--labels", default=None,
                                      help="Comma-separated Jira labels to assign to domain (default: empty)")

    domain_list_parser = domain_subparsers.add_parser("list", help="List all domains with artifact counts")
    domain_list_parser.add_argument("--format", choices=["json", "table"], default="json", help="Output format")

    _domain_seed_parser = domain_subparsers.add_parser(
        "seed", help="Seed domain-config.yaml from hardcoded label map and filesystem domains"
    )

    _domain_config_parser = domain_subparsers.add_parser(
        "config", help="Show current domain-config.yaml contents (read-only)"
    )

    rebuild_parser = subparsers.add_parser("rebuild-index", help="Rebuild index.md for a domain or all domains")
    rebuild_parser.add_argument("domain", nargs="?", default=None, help="Domain to rebuild (default: all domains)")
    rebuild_parser.add_argument("--vault", default=None, help="Vault root path")

    ingest_parser = subparsers.add_parser(
        "ingest-clippings",
        help="Process web clippings from raw/inbound/clippings/ into wiki/"
    )
    ingest_parser.add_argument("--vault", default=None, help="Vault root path")
    ingest_parser.add_argument("--dry-run", action="store_true",
                               help="Show what would be processed without writing files")
    ingest_parser.add_argument("--notify", action="store_true",
                               help="Send Telegram notification after processing")

    jira_parser = subparsers.add_parser(
        "jira-sync",
        help="Sync Jira issues to vault (fetch, diff, write)"
    )
    jira_parser.add_argument("--vault", default=None, help="Vault root path")
    jira_parser.add_argument("--notify", action="store_true", help="Send Telegram notification on completion")
    jira_parser.add_argument("--dry-run", action="store_true", help="Show diff without writing files")

    jira_import_parser = subparsers.add_parser(
        "jira-import",
        help="Import a single Jira issue by key"
    )
    jira_import_parser.add_argument("key", help="Jira issue key (e.g. GO-153)")
    jira_import_parser.add_argument("--vault", default=None, help="Vault root path")

    jira_create_parser = subparsers.add_parser(
        "jira-create",
        help="Create a Jira issue from a vault file"
    )
    jira_create_parser.add_argument("--file", required=True, help="Vault filename (e.g. my-task.md)")
    jira_create_parser.add_argument("--project", required=True, help="Jira project key (e.g. GO)")
    jira_create_parser.add_argument("--type", default="Task", help="Issue type: Task, Bug, Story, Epic (default: Task)")
    jira_create_parser.add_argument("--summary", default="", help="Override title (uses frontmatter title if empty)")
    jira_create_parser.add_argument("--epic", default="", help="Epic key to link to (e.g. GO-100)")
    jira_create_parser.add_argument("--vault", default=None, help="Vault path (default: VAULT_PATH env)")

    jira_projects_parser = subparsers.add_parser(
        "jira-projects",
        help="List accessible Jira projects"
    )
    jira_projects_parser.add_argument("--vault", default=None, help="Vault path (default: VAULT_PATH env)")

    jira_epics_parser = subparsers.add_parser(
        "jira-epics",
        help="List open epics for a Jira project"
    )
    jira_epics_parser.add_argument("--project", required=True, help="Jira project key (e.g. GO)")
    jira_epics_parser.add_argument("--vault", default=None, help="Vault path (default: VAULT_PATH env)")

    jira_issue_types_parser = subparsers.add_parser(
        "jira-issue-types",
        help="List issue types for a Jira project"
    )
    jira_issue_types_parser.add_argument("--project", required=True, help="Jira project key (e.g. GO)")
    jira_issue_types_parser.add_argument("--vault", default=None, help="Vault path (default: VAULT_PATH env)")

    lint_parser = subparsers.add_parser("lint", help="Run vault health checks")
    lint_parser.add_argument("--vault", default=None, help="Vault root path")

    health_parser = subparsers.add_parser("health", help="Calculate vault health score")
    health_parser.add_argument("--vault", default=None, help="Vault root path")
    health_parser.add_argument("--save", action="store_true", help="Save score to history file")
    health_parser.add_argument("--json", dest="json_output", action="store_true", help="Output full JSON with trends")

    status_parser = subparsers.add_parser("status", help="Show vault status summary")
    status_parser.add_argument("--vault", default=None, help="Vault root path")

    args = parser.parse_args()
    vault_path = args.vault or os.getenv("VAULT_PATH", "/vault")

    logger.info(f"Command: {args.command}, vault: {vault_path}")

    if args.command == "enrich":
        from .enricher import enrich
        result = enrich(args.filepath, vault_path, dry_run=args.dry_run)
        _output_json(result)
        sys.exit(0 if result["status"] == "ok" else (2 if result["status"] == "skip" else 1))

    elif args.command == "synthesize":
        from .synthesizer import synthesize
        result = synthesize(vault_path, notify=args.notify, min_ideas=args.min_ideas, dry_run=args.dry_run)
        _output_json(result)
        sys.exit(0 if result["status"] in ("ok", "skip") else 1)

    elif args.command == "watch":
        from .watcher import start_watch
        start_watch(vault_path)

    elif args.command == "index":
        from .vault_index import build_index
        index = build_index(vault_path)
        if args.format == "json":
            _output_json({"entries": [_entry_to_dict(e) for e in index.entries], "count": len(index.entries)})
        else:
            _print_table(index)

    elif args.command == "fetch-meetings":
        from .meeting_fetcher.fetcher import fetch_new_meetings
        result = fetch_new_meetings(vault_path, notify=args.notify, dry_run=args.dry_run)
        _output_json(result)
        sys.exit(0 if result["status"] in ("ok", "skip") else 1)

    elif args.command == "domain":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        logger.info(f"domain subcommand: {args.domain_command}, vault: {vault_path}")

        if args.domain_command == "create":
            from . import domain_config as _dc
            from .domain_manager import create_domain
            try:
                path = create_domain(args.name)
                logger.info(f"domain create: created domain={args.name!r} at {path}")

                # Apply optional overrides to domain-config.yaml if any flag provided
                has_overrides = (
                    args.display_name is not None
                    or args.color is not None
                    or args.labels is not None
                )
                if has_overrides:
                    display_name = args.display_name if args.display_name is not None else args.name
                    color = args.color if args.color is not None else "#607D8B"
                    labels_raw = args.labels if args.labels is not None else ""
                    jira_labels = [lbl.strip() for lbl in labels_raw.split(",") if lbl.strip()] if labels_raw else []
                    entry = {
                        "display_name": display_name,
                        "color": color,
                        "jira_labels": jira_labels,
                    }
                    try:
                        _dc.set_domain(args.name, entry)
                        logger.info(
                            "domain create: updated domain-config.yaml for domain=%r "
                            "display_name=%r color=%r labels=%r",
                            args.name, display_name, color, jira_labels,
                        )
                    except ValueError as cfg_err:
                        logger.error(
                            "domain create: scaffold succeeded but domain-config update failed "
                            "for domain=%r: %s", args.name, cfg_err
                        )
                        _output_json({
                            "status": "error",
                            "message": f"Scaffold created at {path} but config update failed: {cfg_err}",
                            "domain": args.name,
                            "path": str(path),
                        })
                        sys.exit(1)

                _output_json({"status": "ok", "domain": args.name, "path": str(path)})
                sys.exit(0)
            except ValueError as e:
                logger.error(f"domain create: failed for name={args.name!r}: {e}")
                _output_json({"status": "error", "message": str(e)})
                sys.exit(1)

        elif args.domain_command == "list":
            from .domain_manager import list_domains
            domains = list_domains()
            logger.info(f"domain list: found {len(domains)} domains")
            if args.format == "json":
                _output_json({"status": "ok", "domains": domains, "count": len(domains)})
            else:
                _print_domains_table(domains)
            sys.exit(0)

        elif args.domain_command == "seed":
            from . import domain_config as _dc
            from . import vault_paths as _vp_seed
            try:
                from .jira_fetcher.mapper import LABEL_TO_DOMAIN
            except ImportError as imp_err:
                logger.error("domain seed: failed to import LABEL_TO_DOMAIN: %s", imp_err)
                _output_json({"status": "error", "message": f"Import error: {imp_err}"})
                sys.exit(1)

            existing_domains = _vp_seed.all_domains()
            config_existed = _dc.config_path().exists()
            try:
                result_config = _dc.seed_from_defaults(LABEL_TO_DOMAIN, existing_domains)
                n_domains = len(result_config.get("domains", {}))
                if config_existed:
                    msg = f"Config already exists ({n_domains} domains)"
                    logger.info("domain seed: %s", msg)
                    print(msg)
                else:
                    msg = f"Seeded {n_domains} domains"
                    logger.info("domain seed: %s", msg)
                    print(msg)
                _output_json({"status": "ok", "domains": n_domains, "existed": config_existed})
                sys.exit(0)
            except Exception as seed_err:
                logger.error("domain seed: failed: %s", seed_err)
                _output_json({"status": "error", "message": str(seed_err)})
                sys.exit(1)

        elif args.domain_command == "config":
            from . import domain_config as _dc
            try:
                import yaml as _yaml
            except ImportError as imp_err:
                logger.error("domain config: yaml not available: %s", imp_err)
                print(f"Error: PyYAML is not installed — cannot format output. ({imp_err})")
                sys.exit(1)

            config = _dc.load()
            domains = config.get("domains", {})
            if not domains:
                msg = "No domain-config.yaml found. Run 'domain seed' to create."
                logger.info("domain config: %s", msg)
                print(msg)
                sys.exit(0)

            logger.info("domain config: loaded %d domain(s)", len(domains))
            print(_yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120))
            sys.exit(0)

    elif args.command == "rebuild-index":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from .domain_manager import _ARTIFACT_TYPES, update_domain_index
        from .vault_paths import all_domains

        if args.domain:
            target_domains = [args.domain]
        else:
            target_domains = all_domains()

        logger.info(f"rebuild-index: rebuilding for domains={target_domains}")
        rebuilt = []
        for domain in target_domains:
            for artifact_type in _ARTIFACT_TYPES:
                try:
                    index_path = update_domain_index(domain, artifact_type)
                    artifact_dir = index_path.parent
                    entries = sum(
                        1 for f in artifact_dir.glob("*.md")
                        if f.name not in ("index.md", "log.md")
                    )
                    rebuilt.append({"domain": domain, "artifact_type": artifact_type, "entries": entries})
                    logger.info(
                        f"rebuild-index: rebuilt domain={domain!r} artifact_type={artifact_type!r} entries={entries}"
                    )
                except Exception as exc:
                    logger.error(
                        f"rebuild-index: failed for domain={domain!r} artifact_type={artifact_type!r}: {exc}"
                    )
        logger.info(f"rebuild-index: total_indices={len(rebuilt)}")
        _output_json({"status": "ok", "rebuilt": rebuilt, "total_indices": len(rebuilt)})
        sys.exit(0)

    elif args.command == "ingest-clippings":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from .ingest import ingest_batch
        logger.info("ingest-clippings: starting, vault=%s, dry_run=%s, notify=%s",
                    vault_path, args.dry_run, args.notify)
        result = ingest_batch(dry_run=args.dry_run, notify=args.notify)
        logger.info("ingest-clippings: completed, status=%s", result.get("status"))
        _output_json(result)
        sys.exit(0 if result["status"] in ("ok", "skip") else 1)

    elif args.command == "jira-sync":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from .jira_fetcher.fetcher import sync
        logger.info(f"jira-sync: starting sync, vault={vault_path}, notify={args.notify}, dry_run={args.dry_run}")
        result = sync(vault_path, notify=args.notify, dry_run=args.dry_run)
        logger.info(f"jira-sync: completed, status={result.get('status')}")
        _output_json(result)
        sys.exit(0 if result["status"] in ("ok", "skip") else 1)

    elif args.command == "jira-import":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from .jira_fetcher.fetcher import import_single_issue
        logger.info("jira-import: importing key=%s, vault=%s", args.key, vault_path)
        result = import_single_issue(args.key, vault_path)
        logger.info("jira-import: completed, status=%s", result.get("status"))
        _output_json(result)
        sys.exit(0 if result["status"] == "ok" else 1)

    elif args.command == "jira-create":
        vault = args.vault or os.environ.get("VAULT_PATH", "")
        if not vault:
            print(json.dumps({"status": "error", "message": "VAULT_PATH not set"}))
            sys.exit(1)
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault)
        from .jira_fetcher.fetcher import create_and_sync
        logger.info(
            "jira-create: file=%s, project=%s, type=%s, epic=%s, vault=%s",
            args.file, args.project, args.type, args.epic, vault
        )
        result = create_and_sync(
            vault_path=vault,
            filename=args.file,
            project_key=args.project,
            issue_type=args.type,
            summary=args.summary,
            epic_key=args.epic,
        )
        logger.info("jira-create: completed, status=%s", result.get("status"))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result.get("status") in ("ok", "already_exists") else 1)

    elif args.command == "jira-projects":
        try:
            from .jira_fetcher import client
            logger.info("jira-projects: fetching accessible projects")
            projects = client.get_projects()
            result = {
                "status": "ok",
                "projects": [{"key": p["key"], "name": p["name"]} for p in projects]
            }
            logger.info("jira-projects: completed, count=%d", len(projects))
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            logger.error("jira-projects: failed: %s", e)
            print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
            sys.exit(1)

    elif args.command == "jira-epics":
        try:
            from .jira_fetcher import client
            logger.info("jira-epics: fetching epics for project=%s", args.project)
            epics = client.get_project_epics(args.project)
            result = {"status": "ok", "epics": epics}
            logger.info("jira-epics: completed, count=%d", len(epics))
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            logger.error("jira-epics: failed: %s", e)
            print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
            sys.exit(1)

    elif args.command == "jira-issue-types":
        try:
            from .jira_fetcher import client
            logger.info("jira-issue-types: fetching types for project=%s", args.project)
            issue_types = client.get_project_issue_types(args.project)
            result = {"status": "ok", "issue_types": issue_types}
            logger.info("jira-issue-types: completed, count=%d", len(issue_types))
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            logger.error("jira-issue-types: failed: %s", e)
            print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
            sys.exit(1)

    elif args.command == "lint":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from .linter import lint
        logger.info("lint: starting vault health check, vault=%s", vault_path)
        result = lint(vault_path)
        logger.info("lint: completed, total_issues=%d", result["summary"]["total_issues"])
        _output_json(result)
        sys.exit(0)

    elif args.command == "health":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from datetime import datetime, timezone

        from .health_scorer import calculate_health, load_history, save_history

        logger.info("health: starting, vault=%s, save=%s, json=%s", vault_path, args.save, args.json_output)

        result = calculate_health(vault_path)
        logger.info("health: score=%d grade=%s", result["score"], result["grade"])

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if args.save:
            entry = {
                "date": today,
                "calculated_at": result["calculated_at"],
                "score": result["score"],
                "grade": result["grade"],
                "breakdown": {k: {"count": v.get("count", 0), "penalty": v.get("penalty", 0)} for k, v in result["breakdown"].items()},
            }
            save_history(vault_path, entry)
            logger.info("health: saved history entry for date=%s", today)

        if args.json_output:
            history = load_history(vault_path, days=90)
            trend_7d = [{"date": e["date"], "score": e["score"]} for e in history[-7:]]
            trend_30d = [{"date": e["date"], "score": e["score"]} for e in history[-30:]]
            output = {
                "score": result["score"],
                "grade": result["grade"],
                "breakdown": result["breakdown"],
                "trend_7d": trend_7d,
                "trend_30d": trend_30d,
                "calculated_at": result["calculated_at"],
            }
            _output_json(output)
        else:
            # Human-readable output
            print(f"Vault Health Score: {result['score']}/100 ({result['grade'].upper()})")
            print(f"Calculated at: {result['calculated_at']}")
            print()
            for key, data in result["breakdown"].items():
                count = data.get("count", data.get("pct", "—"))
                penalty = data.get("penalty", 0)
                print(f"  {key}: {count} (penalty: -{penalty})")

        sys.exit(0)

    elif args.command == "status":
        from . import vault_paths as _vp
        _vp.VAULT_PATH = __import__("pathlib").Path(vault_path)
        from .domain_manager import list_domains
        from .linter import lint

        logger.info("status: collecting vault status, vault=%s", vault_path)

        domains = list_domains()
        lint_result = lint(vault_path)

        raw_root = _vp.VAULT_PATH / "raw" / "inbound"
        raw_counts = {}
        if raw_root.exists():
            for subdir in raw_root.iterdir():
                if subdir.is_dir():
                    count = sum(1 for f in subdir.iterdir() if f.is_file())
                    raw_counts[subdir.name] = count

        total_artifacts = sum(d.get("total", 0) for d in domains)

        result = {
            "status": "ok",
            "domains": domains,
            "domains_count": len(domains),
            "total_artifacts": total_artifacts,
            "raw_counts": raw_counts,
            "health": lint_result["summary"],
        }
        logger.info("status: completed, domains=%d, total_artifacts=%d, issues=%d",
                    len(domains), total_artifacts, lint_result["summary"]["total_issues"])
        _output_json(result)
        sys.exit(0)


def _output_json(data):
    import json
    print(json.dumps(data, ensure_ascii=False))


def _entry_to_dict(entry):
    return {
        "path": entry.path,
        "title": entry.title,
        "tags": entry.tags,
        "keywords": entry.keywords,
        "category": entry.category,
        "domain": entry.domain,
    }


def _print_table(index):
    print(f"{'Path':<50} {'Title':<30} {'Domain':<18} {'Category':<12} {'Tags'}")
    print("-" * 140)
    for e in index.entries:
        tags_str = ", ".join(e.tags[:3])
        print(f"{e.path:<50} {e.title[:28]:<30} {e.domain:<18} {e.category:<12} {tags_str}")
    print(f"\nTotal: {len(index.entries)} entries")


def _print_domains_table(domains: list) -> None:
    header = f"{'Name':<24} {'Ideas':>6} {'PRDs':>5} {'Epics':>6} {'Stories':>8} {'Tasks':>6} {'Bugs':>5} {'Total':>6}  {'Last Updated'}"
    print(header)
    print("-" * len(header))
    for d in domains:
        print(
            f"{d['name']:<24} {d['ideas']:>6} {d['prds']:>5} {d['epics']:>6} "
            f"{d['userstories']:>8} {d['tasks']:>6} {d['bugs']:>5} {d['total']:>6}  {d['last_updated']}"
        )
    print(f"\nTotal: {len(domains)} domain(s)")
