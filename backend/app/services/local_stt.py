import io
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import av
import numpy as np

log = logging.getLogger("weathergpt.stt")

ROOT = Path(__file__).resolve().parent.parent.parent / "models" / "stt"
INDIC = ROOT / "indic_conformer"
WHISPER_EN = ROOT / "whisper_en"
SAMPLE_RATE = 16000
BLANK_ID = 256
MAX_SECONDS = 60


class SpeechError(Exception):
    pass


def decode_audio(data: bytes) -> np.ndarray:
    try:
        container = av.open(io.BytesIO(data))
    except av.error.FFmpegError as exc:
        raise SpeechError(f"unreadable audio: {exc}") from exc
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    try:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    except av.error.FFmpegError as exc:
        if not chunks:
            raise SpeechError(f"could not decode audio: {exc}") from exc
    finally:
        container.close()
    if not chunks:
        raise SpeechError("no audio in recording")
    audio = np.concatenate(chunks).astype(np.float32)
    return audio[: SAMPLE_RATE * MAX_SECONDS]


def normalise(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    return audio if peak < 1e-4 else (audio / peak * 0.9).astype(np.float32)


def _threads() -> int:
    return max(1, min(4, (os.cpu_count() or 2) // 2))


class IndicConformer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: tuple[Any, Any, Any] | None = None
        self.vocab: dict[str, list[str]] = {}
        self.masks: dict[str, np.ndarray] = {}

    @staticmethod
    def installed() -> bool:
        return all((INDIC / name).exists() for name in ("preprocessor.onnx", "encoder.onnx", "ctc_decoder.onnx", "vocab.json", "language_masks.json"))

    def languages(self) -> list[str]:
        if not self.installed():
            return []
        self._load()
        return sorted(self.masks)

    def _load(self) -> tuple[Any, Any, Any]:
        if self._sessions:
            return self._sessions
        with self._lock:
            if self._sessions:
                return self._sessions
            import onnxruntime as ort

            started = time.perf_counter()
            options = ort.SessionOptions()
            options.intra_op_num_threads = _threads()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            providers = ["CPUExecutionProvider"]
            sessions = tuple(
                ort.InferenceSession(str(INDIC / name), sess_options=options, providers=providers)
                for name in ("preprocessor.onnx", "encoder.onnx", "ctc_decoder.onnx")
            )
            self.vocab = json.loads((INDIC / "vocab.json").read_text(encoding="utf-8"))
            self.masks = {k: np.asarray(v, dtype=bool) for k, v in json.loads((INDIC / "language_masks.json").read_text(encoding="utf-8")).items()}
            self._sessions = sessions
            log.info("IndicConformer loaded in %.1fs", time.perf_counter() - started)
            return sessions

    def logprobs(self, audio: np.ndarray) -> np.ndarray:
        preprocessor, encoder, decoder = self._load()
        signal = audio.reshape(1, -1).astype(np.float32)
        features, feature_length = preprocessor.run(["features", "features_length"], {"input_signal": signal, "length": np.array([signal.shape[1]], dtype=np.int64)})
        encoded, _ = encoder.run(["outputs", "encoded_lengths"], {"audio_signal": features, "length": feature_length})
        return decoder.run(["logprobs"], {"encoder_output": encoded})[0][0]

    def decode(self, logprobs: np.ndarray, language: str) -> tuple[str, float]:
        masked = logprobs[:, self.masks[language]]
        masked = masked - masked.max(axis=-1, keepdims=True)
        log_softmax = masked - np.log(np.exp(masked).sum(axis=-1, keepdims=True))
        best = log_softmax.argmax(axis=-1)
        peaks = log_softmax.max(axis=-1)
        speech = best != BLANK_ID
        confidence = float(np.exp(peaks[speech].mean())) if speech.any() else 0.0
        tokens: list[int] = []
        previous = -1
        for index in best:
            if index != previous and index != BLANK_ID:
                tokens.append(int(index))
            previous = index
        vocab = self.vocab[language]
        text = "".join(vocab[i] for i in tokens).replace("▁", " ")
        return " ".join(text.split()), confidence

    def transcribe(self, audio: np.ndarray, language: str) -> dict[str, Any]:
        logprobs = self.logprobs(audio)
        if language not in self.masks:
            raise SpeechError(f"IndicConformer does not support {language}")
        text, confidence = self.decode(logprobs, language)
        return {"text": text, "language": language, "confidence": round(confidence, 3)}


class WhisperEnglish:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recognizer: Any = None

    @staticmethod
    def installed() -> bool:
        return all((WHISPER_EN / name).exists() for name in ("base.en-encoder.int8.onnx", "base.en-decoder.int8.onnx", "base.en-tokens.txt"))

    def _load(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        with self._lock:
            if self._recognizer is None:
                import sherpa_onnx

                self._recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=str(WHISPER_EN / "base.en-encoder.int8.onnx"),
                    decoder=str(WHISPER_EN / "base.en-decoder.int8.onnx"),
                    tokens=str(WHISPER_EN / "base.en-tokens.txt"),
                    language="en",
                    task="transcribe",
                    num_threads=_threads(),
                )
            return self._recognizer

    def transcribe(self, audio: np.ndarray) -> dict[str, Any]:
        recognizer = self._load()
        stream = recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio)
        recognizer.decode_stream(stream)
        return {"text": " ".join(stream.result.text.split()), "language": "en"}


indic = IndicConformer()
english = WhisperEnglish()


def available() -> dict[str, Any]:
    return {"indic": indic.installed(), "english": english.installed()}


def transcribe(data: bytes, language: str) -> dict[str, Any]:
    started = time.perf_counter()
    audio = normalise(decode_audio(data))
    seconds = round(audio.size / SAMPLE_RATE, 2)
    if seconds < 0.3:
        raise SpeechError("recording too short")
    if language == "en":
        if not english.installed():
            raise SpeechError("English speech model not installed")
        result = english.transcribe(audio) | {"engine": "whisper-base.en (local)"}
    elif indic.installed():
        result = indic.transcribe(audio, language) | {"engine": "IndicConformer-600M (local)"}
    else:
        raise SpeechError("Indian-language speech model not installed")
    return result | {"audio_seconds": seconds, "seconds": round(time.perf_counter() - started, 2)}
