import logging
from dataclasses import dataclass

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    name: str
    model: str
    max_tokens: int
    timeout_seconds: int
    prompt_file: str


@dataclass
class PipelineConfig:
    agents: dict[str, AgentConfig]
    notification_enabled: bool
    notify_on_complete: bool
    notify_on_failure: bool
    vault_context_max_entries: int


def load_config(yaml_path: str) -> PipelineConfig:
    with open(yaml_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    defaults = raw.get("defaults", {})
    default_model = defaults.get("model", "claude-sonnet-4-6")
    default_max_tokens = defaults.get("max_tokens", 4096)
    default_timeout = defaults.get("timeout_seconds", 120)

    agents_raw = raw.get("agents", {})
    agents: dict[str, AgentConfig] = {}

    for agent_name, agent_section in agents_raw.items():
        agent_section = agent_section or {}

        model = agent_section.get("model", default_model)
        max_tokens = agent_section.get("max_tokens", default_max_tokens)
        timeout_seconds = agent_section.get("timeout_seconds", default_timeout)
        prompt_file = agent_section.get("prompt_file", "")

        cfg = AgentConfig(
            name=agent_name,
            model=model,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            prompt_file=prompt_file,
        )
        agents[agent_name] = cfg
        logger.info(
            "Agent %s: model=%s, max_tokens=%d",
            agent_name,
            cfg.model,
            cfg.max_tokens,
        )

    notification = raw.get("notification", {})
    notification_enabled = bool(notification.get("enabled", False))
    notify_on_complete = bool(notification.get("on_complete", False))
    notify_on_failure = bool(notification.get("on_failure", False))

    analyst_section = agents_raw.get("analyst") or {}
    vault_context = analyst_section.get("vault_context") or {}
    vault_context_max_entries = int(vault_context.get("max_entries", 10))

    logger.info(
        "Config loaded from %s: %d agents", yaml_path, len(agents)
    )

    return PipelineConfig(
        agents=agents,
        notification_enabled=notification_enabled,
        notify_on_complete=notify_on_complete,
        notify_on_failure=notify_on_failure,
        vault_context_max_entries=vault_context_max_entries,
    )
