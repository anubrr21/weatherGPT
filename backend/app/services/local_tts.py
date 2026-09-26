import array
import asyncio
import io
import threading
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "models" / "tts"

_engines: dict[str, object] = {}
_lock = threading.Lock()


def _installed() -> list[Path]:
    if not (ROOT / "espeak-ng-data").exists():
        return []
    return [p for p in ROOT.iterdir() if (p / "model.onnx").exists() and (p / "tokens.txt").exists()]


def _low_quality(folder: Path) -> bool:
    marker = folder / "quality.txt"
    return marker.exists() and marker.read_text(encoding="utf-8").strip() == "low"


def available_languages() -> list[str]:
    return sorted(p.name for p in _installed() if not _low_quality(p))


def last_resort_languages() -> list[str]:
    return sorted(p.name for p in _installed() if _low_quality(p))


def _speaker(lang: str) -> int:
    marker = ROOT / lang / "speaker.txt"
    return int(marker.read_text(encoding="utf-8").strip()) if marker.exists() else 0


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
    audio = _engine(lang).generate(text, sid=_speaker(lang), speed=speed)
    pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in audio.samples))
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(audio.sample_rate)
        dst.writeframes(pcm.tobytes())
    return out.getvalue()


async def synthesize(lang: str, text: str, speed: float = 0.95, allow_low_quality: bool = False) -> bytes | None:
    if lang not in available_languages() and not (allow_low_quality and lang in last_resort_languages()):
        return None
    return await asyncio.to_thread(_render, lang, text, speed)


def warm(languages: list[str]) -> None:
    for lang in languages:
        if lang in available_languages():
            _engine(lang)
