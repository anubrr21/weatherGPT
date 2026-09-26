import asyncio
import io
import math
import struct
import wave

import pytest

from app.services import local_stt, local_tts, voice


def _tone_wav(seconds: float = 1.0, rate: int = 22050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate))))
    return buffer.getvalue()


def test_opus_is_much_smaller_and_decodes_back():
    wav = _tone_wav(2.0)
    opus = voice.to_opus(wav)
    assert opus[:4] == b"OggS"
    assert len(opus) * 8 < len(wav)
    decoded = local_stt.decode_audio(opus)
    assert abs(decoded.size / local_stt.SAMPLE_RATE - 2.0) < 0.1


def test_short_or_empty_audio_is_rejected():
    with pytest.raises(local_stt.SpeechError):
        local_stt.decode_audio(b"not audio at all")


needs_models = pytest.mark.skipif(
    not (local_stt.indic.installed() and "hi" in local_tts.available_languages()),
    reason="IndicConformer or Piper Hindi voice not installed",
)


@needs_models
def test_hindi_round_trip_through_opus():
    sentence = "कल जयपुर में तेज़ बारिश की संभावना है"
    wav = asyncio.run(local_tts.synthesize("hi", sentence))
    result = local_stt.transcribe(voice.to_opus(wav), "hi")
    heard = result["text"].replace("ज़", "ज").split()
    expected = sentence.replace("ज़", "ज").split()
    assert sum(1 for word in expected if word in heard) >= len(expected) - 1
    assert result["engine"].startswith("IndicConformer")


@needs_models
def test_telugu_uses_telugu_script():
    if "te" not in local_tts.available_languages():
        pytest.skip("no Telugu voice")
    wav = asyncio.run(local_tts.synthesize("te", "రేపు గుంటూరులో భారీ వర్షం"))
    text = local_stt.transcribe(wav, "te")["text"]
    assert any("ఀ" <= ch <= "౿" for ch in text)
