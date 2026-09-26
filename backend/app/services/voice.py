import array
import base64
import difflib
import hashlib
import io
import logging
import unicodedata
import wave

from app.config import get_settings
from app.services import providers
from app.services.http import TTLCache, client

TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_LANGS = {"en", "hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "as"}

_tts_cache = TTLCache(ttl_s=3600, max_items=128)
MIN_MATCH = 0.45
log = logging.getLogger("weathergpt.voice")


class VoiceError(Exception):
    pass


def _trim_silence(wav_bytes: bytes, threshold: int = 500, pad_s: float = 0.15) -> bytes:
    with wave.open(io.BytesIO(wav_bytes)) as src:
        params = src.getparams()
        if params.sampwidth != 2 or params.nchannels != 1:
            return wav_bytes
        pcm = array.array("h", src.readframes(params.nframes))
    loud = [i for i in range(0, len(pcm), 64) if abs(pcm[i]) > threshold]
    if not loud:
        return wav_bytes
    pad = int(params.framerate * pad_s)
    start = max(loud[0] - pad, 0)
    end = min(loud[-1] + pad, len(pcm))
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(params.framerate)
        dst.writeframes(pcm[start:end].tobytes())
    return out.getvalue()


def _letters(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text.lower()) if ch.isalpha())


def similarity(expected: str, heard: str) -> float:
    a, b = _letters(expected), _letters(heard)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


async def _verified(audio: bytes, text: str, language: str | None) -> float | None:
    if not get_settings().groq_api_key.strip() or language not in WHISPER_LANGS:
        return None
    try:
        heard = await transcribe(audio, "check.wav", "audio/wav", language)
    except VoiceError:
        return None
    return similarity(text, heard["text"])


async def synthesize(text: str, voice: str = "Kore", language: str | None = None) -> bytes:
    settings = get_settings()
    if not settings.gemini_api_key.strip():
        raise VoiceError("No Gemini key for neural voice")
    text = text.strip()[:1200]
    if not text:
        raise VoiceError("Nothing to say")
    key = hashlib.sha1(f"{voice}|{language}|{text}".encode()).hexdigest()

    async def load() -> bytes:
        last = "no TTS model configured"
        for model in settings.tts_models:
            bench_key = f"tts:{model}"
            if providers.cooling(bench_key):
                continue
            response = await client().post(
                TTS_URL.format(model=model),
                headers={"x-goog-api-key": settings.gemini_api_key},
                json={
                    "contents": [{"parts": [{"text": text}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
                    },
                },
                timeout=45,
            )
            if response.status_code >= 400:
                last = f"{model}: {response.status_code}"
                providers.bench(bench_key, providers.ProviderError(response.text[:300], response.status_code, providers.parse_retry_after(response.text)))
                continue
            try:
                part = response.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            except (KeyError, IndexError, ValueError):
                last = f"{model}: no audio returned"
                continue
            audio = base64.b64decode(part["data"])
            if not audio.startswith(b"RIFF"):
                last = f"{model}: unexpected audio format {part.get('mimeType')}"
                continue
            audio = _trim_silence(audio)
            score = await _verified(audio, text, language)
            if score is not None and score < MIN_MATCH:
                last = f"{model}: spoken audio did not match the text (match {score:.2f})"
                log.warning("tts mismatch %s score=%.2f", model, score)
                continue
            providers.succeeded(bench_key)
            return audio
        raise VoiceError(f"Neural voice unavailable ({last})")

    return await _tts_cache.get_or_set(key, load)


async def transcribe(audio: bytes, filename: str, content_type: str, language: str | None) -> dict:
    settings = get_settings()
    if not settings.groq_api_key.strip():
        raise VoiceError("No Groq key for speech recognition")
    data = {"model": settings.stt_model, "response_format": "json", "temperature": "0"}
    if language in WHISPER_LANGS:
        data["language"] = language
    response = await client().post(
        STT_URL,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        data=data,
        files={"file": (filename, audio, content_type or "audio/webm")},
        timeout=45,
    )
    if response.status_code >= 400:
        raise VoiceError(f"Speech recognition failed ({response.status_code}): {response.text[:200]}")
    return {"text": (response.json().get("text") or "").strip(), "model": settings.stt_model, "language": data.get("language", "auto")}
