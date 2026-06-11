import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_model = None
_stt_enabled = os.getenv("STT_ENABLED", "1").lower() not in ("0", "false", "no")


def init_model(
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
) -> None:
    global _model
    if not _stt_enabled:
        logger.info("STT отключен через STT_ENABLED=0, пропускаем загрузку модели")
        return
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        logger.warning("faster_whisper недоступен, STT отключен: %s", e)
        return
    logger.info("Загрузка модели Whisper '%s' (device=%s, compute_type=%s)...", model_size, device, compute_type)
    start = time.time()
    _model = WhisperModel(model_size, device=device, compute_type=compute_type)
    elapsed = time.time() - start
    logger.info("Модель Whisper загружена за %.1fs", elapsed)


def transcribe(audio_path: str) -> str:
    if _model is None:
        raise RuntimeError("Whisper model not initialized. Call init_model() first or check STT_ENABLED.")
    logger.info("Транскрибация аудио: %s", Path(audio_path).name)
    start = time.time()
    segments, info = _model.transcribe(audio_path, language=None)
    text = " ".join(segment.text for segment in segments).strip()
    elapsed = time.time() - start
    logger.info(
        "Транскрибация завершена: %d символов, язык=%s (prob=%.2f), время %.1fs",
        len(text), info.language, info.language_probability, elapsed,
    )
    return text
