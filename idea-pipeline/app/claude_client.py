import logging
import time

import anthropic

logger = logging.getLogger(__name__)

_RATE_LIMIT_MAX_RETRIES = 2
_RATE_LIMIT_BACKOFF_SECONDS = 5
_TIMEOUT_EXTRA_SECONDS = 30


class PipelineClaudeClient:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def call(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        timeout: int,
    ) -> str:
        logger.info(
            "Claude call started: model=%s, system_prompt_len=%d, user_message_len=%d, max_tokens=%d",
            model,
            len(system_prompt),
            len(user_message),
            max_tokens,
        )

        rate_limit_attempts = 0
        current_timeout = timeout

        while True:
            started_at = time.monotonic()
            try:
                response = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    timeout=current_timeout,
                )
                latency = time.monotonic() - started_at
                output_text = response.content[0].text
                logger.info(
                    "Claude call succeeded: model=%s, output_len=%d, latency=%.2fs",
                    model,
                    len(output_text),
                    latency,
                )
                return output_text

            except anthropic.RateLimitError as exc:
                rate_limit_attempts += 1
                if rate_limit_attempts > _RATE_LIMIT_MAX_RETRIES:
                    logger.error(
                        "Claude call failed: model=%s, error_type=RateLimitError, "
                        "attempts=%d, message=%s",
                        model,
                        rate_limit_attempts,
                        str(exc),
                    )
                    raise
                logger.warning(
                    "Claude call retry: reason=rate_limit, attempt=%d/%d, backoff=%ds, model=%s",
                    rate_limit_attempts,
                    _RATE_LIMIT_MAX_RETRIES,
                    _RATE_LIMIT_BACKOFF_SECONDS,
                    model,
                )
                time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)

            except anthropic.APITimeoutError as exc:
                # Only one retry on timeout with an extended timeout window
                logger.warning(
                    "Claude call retry: reason=timeout, attempt=1/1, "
                    "new_timeout=%ds, model=%s",
                    current_timeout + _TIMEOUT_EXTRA_SECONDS,
                    model,
                )
                current_timeout = current_timeout + _TIMEOUT_EXTRA_SECONDS
                try:
                    started_at = time.monotonic()
                    response = self._client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_message}],
                        timeout=current_timeout,
                    )
                    latency = time.monotonic() - started_at
                    output_text = response.content[0].text
                    logger.info(
                        "Claude call succeeded after timeout retry: model=%s, "
                        "output_len=%d, latency=%.2fs",
                        model,
                        len(output_text),
                        latency,
                    )
                    return output_text
                except Exception as retry_exc:
                    logger.error(
                        "Claude call failed after timeout retry: model=%s, "
                        "error_type=%s, message=%s",
                        model,
                        type(retry_exc).__name__,
                        str(retry_exc),
                    )
                    raise retry_exc from exc

            except anthropic.APIError as exc:
                logger.error(
                    "Claude call failed: model=%s, error_type=%s, message=%s",
                    model,
                    type(exc).__name__,
                    str(exc),
                )
                raise
