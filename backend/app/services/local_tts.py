import array
import asyncio
import io
import threading
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "models" / "tts"

_engines: dict[str, object] = {}
_lock = threading.Lock()


def available_languages() -> list[str]:
    if not (ROOT / "espeak-ng-data").exists():
        return []
    return sorted(p.name for p in ROOT.iterdir() if (p / "model.onnx").exists() and (p / "tokens.txt").exists())


def _engine(lang: str):
    with _lock:
        if lang not in _engines:
            import sherpa_onnx

            folder = ROOT / lang
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(folder / "model.onnx"),
                        tokens=str(folder / "tokens.txt"),
                        data_dir=str(ROOT / "espeak-ng-data"),
                    ),
                    num_threads=2,
                ),
                max_num_sentences=2,
            )
            _engines[lang] = sherpa_onnx.OfflineTts(config)
        return _engines[lang]


def _render(lang: str, text: str, speed: float) -> bytes:
    audio = _engine(lang).generate(text, sid=0, speed=speed)
    pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in audio.samples))
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(audio.sample_rate)
        dst.writeframes(pcm.tobytes())
    return out.getvalue()


async def synthesize(lang: str, text: str, speed: float = 0.95) -> bytes | None:
    if lang not in available_languages():
        return None
    return await asyncio.to_thread(_render, lang, text, speed)


def warm(languages: list[str]) -> None:
    for lang in languages:
        if lang in available_languages():
            _engine(lang)
