import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_serve(args):
    """Start the HTTP API server."""
    import uvicorn
    from idea_pipeline.api import app

    host = os.getenv("PIPELINE_HOST", "0.0.0.0")
    port = int(os.getenv("PIPELINE_PORT", "8100"))

    logger.info("Starting Idea Pipeline API: host=%s, port=%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


def cmd_run(args):
    """Run a single pipeline without the HTTP server (for debugging)."""
    import asyncio
    from pathlib import Path
    from idea_pipeline.config import load_config
    from idea_pipeline.claude_client import PipelineClaudeClient
    from idea_pipeline.state import PipelineStore
    from idea_pipeline.orchestrator import PipelineOrchestrator
    from idea_pipeline import vault_writer
    from slugify import slugify

    vault_path = Path(os.getenv("VAULT_PATH", "/vault"))
    config_path = os.getenv("PIPELINE_CONFIG", "pipeline.yaml")
    config = load_config(config_path)
    client = PipelineClaudeClient(os.getenv("CLAUDE_API_KEY", ""))
    store = PipelineStore()

    domain = args.domain

    # Get input text
    if args.file:
        file_path = vault_path / args.file
        if not file_path.exists():
            logger.error("File not found: %s", file_path)
            sys.exit(1)
        input_text = file_path.read_text(encoding="utf-8")
        input_type = "file"
        logger.info("Input from file: %s (%d chars)", args.file, len(input_text))
    elif args.text:
        input_text = args.text
        input_type = "text"
        logger.info("Input from text: %d chars", len(input_text))
    else:
        logger.error("Provide --text or --file")
        sys.exit(1)

    slug = slugify(input_text[:40], allow_unicode=True)
    ctx = vault_writer.get_pipeline_context(slug, domain)

    run = store.create(
        slug=slug,
        input_type=input_type,
        started_from=args.start_from,
        vault_dir=str(ctx["ideas_dir"]),
        domain=domain,
    )

    vault_writer.write_input(
        input_text,
        pipeline_id=run.pipeline_id,
        input_type=input_type,
        slug=slug,
        domain=domain,
    )

    orchestrator = PipelineOrchestrator(
        config=config,
        claude_client=client,
        store=store,
        vault_path=vault_path,
    )

    logger.info("Running pipeline %s (domain=%s)...", run.pipeline_id, domain)
    asyncio.run(
        orchestrator.run_pipeline(
            run.pipeline_id, input_text, args.start_from
        )
    )

    final_run = store.get(run.pipeline_id)
    logger.info(
        "Pipeline %s finished: status=%s, artifacts=%d",
        run.pipeline_id,
        final_run.stage.value,
        len(final_run.artifacts),
    )


def cmd_status(args):
    """Show status of a pipeline from _state.json."""
    import json
    from pathlib import Path
    from idea_pipeline.state import PipelineStore

    vault_path = Path(os.getenv("VAULT_PATH", "/vault"))

    # args.pipeline_id could be a full path to pipeline dir or just an ID
    # Try to find the pipeline dir in vault/Pipeline/
    pipeline_base = vault_path / "Pipeline"
    if not pipeline_base.exists():
        logger.error("No Pipeline directory in vault")
        sys.exit(1)

    # Search for matching directory
    target_dir = None
    for d in sorted(pipeline_base.iterdir()):
        if not d.is_dir():
            continue
        state_file = d / "_state.json"
        if state_file.exists():
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("pipeline_id", "").startswith(args.pipeline_id):
                target_dir = d
                break

    if target_dir is None:
        logger.error("Pipeline not found: %s", args.pipeline_id)
        sys.exit(1)

    run = PipelineStore.load_state_file(target_dir)
    if run is None:
        logger.error("Could not load state from %s", target_dir)
        sys.exit(1)

    print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        prog="idea_pipeline",
        description="Idea Pipeline — AI-powered idea-to-PRD-to-tasks orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start HTTP API server")
    serve_parser.set_defaults(func=cmd_serve)

    # run
    run_parser = subparsers.add_parser("run", help="Run single pipeline (debug)")
    run_parser.add_argument("--text", type=str, help="Idea text")
    run_parser.add_argument("--file", type=str, help="Path to vault file (relative to vault)")
    run_parser.add_argument(
        "--start-from",
        type=str,
        default="analyst",
        choices=["analyst", "pm", "decomposer"],
        help="Stage to start from (default: analyst)",
    )
    run_parser.add_argument(
        "--domain",
        type=str,
        default="general",
        help="Domain for organizing artifacts (default: general)",
    )
    run_parser.set_defaults(func=cmd_run)

    # status
    status_parser = subparsers.add_parser("status", help="Show pipeline status")
    status_parser.add_argument("pipeline_id", type=str, help="Pipeline ID (or prefix)")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
