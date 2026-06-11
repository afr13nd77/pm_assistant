import logging

from idea_pipeline.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class PMAgent(BaseAgent):
    pass  # Uses BaseAgent.run() and BaseAgent._build_user_message() as-is
