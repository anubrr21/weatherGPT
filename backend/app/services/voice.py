import array
import base64
import difflib
import hashlib
import io
import logging
import re
import unicodedata
import wave

from app.config import get_settings
from app.services import local_tts, providers
from app.services.http import TTLCache, client

TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
AZURE_URL = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
AZURE_VOICES = {
    "en": ("en-IN", "en-IN-NeerjaNeural"),
    "hi": ("hi-IN", "hi-IN-SwaraNeural"),
    "bn": ("bn-IN", "bn-IN-TanishaaNeural"),
    "te": ("te-IN", "te-IN-ShrutiNeural"),
    "ta": ("ta-IN", "ta-IN-PallaviNeural"),
    "mr": ("mr-IN", "mr-IN-AarohiNeural"),
    "gu": ("gu-IN", "gu-IN-DhwaniNeural"),
    "kn": ("kn-IN", "kn-IN-SapnaNeural"),
    "ml": ("ml-IN", "ml-IN-SobhanaNeural"),
    "or": ("or-IN", "or-IN-SubhasiniNeural"),
    "pa": ("pa-IN", "pa-IN-OjasNeural"),
    "as": ("as-IN", "as-IN-YashicaNeural"),
    "ur": ("ur-IN", "ur-IN-GulNeural"),
}
STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_LANGS = {"en", "hi", "bn", "te", "ta", "mr", "gu", "kn", "ml", "pa", "ur", "as"}

_tts_cache = TTLCache(ttl_s=3600, max_items=128)
MIN_MATCH = 0.45
log = logging.getLogger("weathergpt.voice")


class VoiceError(Exception):
    pass


SCRIPTS = [
    ((0x0900, 0x097F), ("hi", "mr")),
    ((0x0980, 0x09FF), ("bn", "as")),
    ((0x0A00, 0x0A7F), ("pa",)),
    ((0x0A80, 0x0AFF), ("gu",)),
    ((0x0B00, 0x0B7F), ("or",)),
    ((0x0B80, 0x0BFF), ("ta",)),
    ((0x0C00, 0x0C7F), ("te",)),
    ((0x0C80, 0x0CFF), ("kn",)),
    ((0x0D00, 0x0D7F), ("ml",)),
    ((0x0600, 0x06FF), ("ur",)),
]


def detect_language(text: str, hint: str | None = None) -> str:
    counts: dict[tuple[str, ...], int] = {}
    latin = 0
    assamese_letters = 0
    for ch in text:
        code = ord(ch)
        if ch.isascii() and ch.isalpha():
            latin += 1
            continue
        if code in (0x09F0, 0x09F1):
            assamese_letters += 1
        for (lo, hi), langs in SCRIPTS:
            if lo <= code <= hi:
                counts[langs] = counts.get(langs, 0) + 1
                break
    if not counts or latin > max(counts.values()):
        return "en"
    langs = max(counts, key=lambda k: counts[k])
    if hint in langs:
        return hint
    if langs == ("bn", "as") and assamese_letters:
        return "as"
    return langs[0]


def _pcm_to_wav(pcm: bytes, mime: str) -> bytes:
    rate = int(m.group(1)) if (m := re.search(r"rate=(\d+)", mime)) else 24000
    channels = int(m.group(1)) if (m := re.search(r"channels=(\d+)", mime)) else 1
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(pcm)
    return out.getvalue()


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
    except VoiceError as exc:
        log.warning("tts verify skipped: %s", exc)
        return None
    score = similarity(text, heard["text"])
    if score < MIN_MATCH:
        log.warning("tts verify lang=%s expected=%r heard=%r", language, text[:80], heard["text"][:80])
    return score


def _ssml(text: str, language: str | None) -> str:
    locale, voice_name = AZURE_VOICES.get(language or "en", AZURE_VOICES["en"])
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<speak version='1.0' xml:lang='{locale}' xmlns='http://www.w3.org/2001/10/synthesis'>"
        f"<voice name='{voice_name}'><prosody rate='-4%'>{safe}</prosody></voice></speak>"
    )


SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_LANGS = {"bn", "en", "gu", "hi", "kn", "ml", "mr", "or", "pa", "ta", "te"}


async def _sarvam(text: str, language: str | None) -> bytes | None:
    settings = get_settings()
    lang = language or "en"
    if not settings.sarvam_api_key.strip() or lang not in SARVAM_LANGS or providers.cooling("tts:sarvam"):
        return None
    body = {
        "text": text,
        "language_code": f"{'od' if lang == 'or' else lang}-IN",
        "model": settings.sarvam_tts_model,
        "output_audio_codec": "wav",
        "speech_sample_rate": 24000,
    }
    if settings.sarvam_speaker.strip():
        body["speaker"] = settings.sarvam_speaker.strip()
    response = await client().post(SARVAM_URL, headers={"api-subscription-key": settings.sarvam_api_key.strip()}, json=body, timeout=30)
    if response.status_code >= 400:
        providers.bench("tts:sarvam", providers.ProviderError(response.text[:200], response.status_code, providers.parse_retry_after(response.text)))
        log.warning("sarvam tts failed %s %s", response.status_code, response.text[:200])
        return None
    try:
        audio = base64.b64decode(response.json()["audios"][0])
    except (KeyError, IndexError, ValueError):
        log.warning("sarvam tts returned no audio")
        return None
    if not audio.startswith(b"RIFF"):
        audio = _pcm_to_wav(audio, "audio/l16; rate=24000; channels=1")
    providers.succeeded("tts:sarvam")
    return _trim_silence(audio)


async def _azure(text: str, language: str | None) -> bytes | None:
    settings = get_settings()
    if not settings.azure_speech_key.strip() or providers.cooling("tts:azure"):
        return None
    response = await client().post(
        AZURE_URL.format(region=settings.azure_speech_region.strip()),
        headers={
            "Ocp-Apim-Subscription-Key": settings.azure_speech_key.strip(),
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "WeatherGPT",
        },
        content=_ssml(text, language).encode("utf-8"),
        timeout=30,
    )
    if response.status_code >= 400 or not response.content.startswith(b"RIFF"):
        providers.bench("tts:azure", providers.ProviderError(response.text[:200], response.status_code))
        log.warning("azure tts failed %s %s", response.status_code, response.text[:200])
        return None
    providers.succeeded("tts:azure")
    return _trim_silence(response.content)


async def synthesize(text: str, voice: str = "Kore", language: str | None = None) -> bytes:
    settings = get_settings()
    language = detect_language(text, language)
    local = language in local_tts.available_languages()
    if not local and language not in local_tts.last_resort_languages() and not settings.gemini_api_key.strip() and not settings.azure_speech_key.strip() and not settings.sarvam_api_key.strip():
        raise VoiceError("No voice available for this language")
    text = text.strip()[:1200]
    if not text:
        raise VoiceError("Nothing to say")
    key = hashlib.sha1(f"{voice}|{language}|{text}".encode()).hexdigest()

    async def load() -> bytes:
        if settings.sarvam_for_all or not local:
            sarvam = await _sarvam(text, language)
            if sarvam:
                return sarvam
        if local:
            try:
                audio = await local_tts.synthesize(language or "en", text)
                if audio:
                    return _trim_silence(audio)
            except Exception as exc:
                log.warning("local tts failed for %s: %s", language, exc)
        azure = await _azure(text, language)
        if azure:
            return azure
        last = "no TTS model configured"
        for model in settings.tts_models if settings.gemini_api_key.strip() else []:
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
            mime = (part.get("mimeType") or "").lower()
            if not audio.startswith(b"RIFF") and ("l16" in mime or "pcm" in mime):
                audio = _pcm_to_wav(audio, mime)
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
        if language in local_tts.last_resort_languages():
            rough = await local_tts.synthesize(language, text, allow_low_quality=True)
            if rough:
                return _trim_silence(rough)
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
