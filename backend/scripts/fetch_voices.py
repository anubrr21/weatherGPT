import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

import onnx

ROOT = Path(__file__).resolve().parent.parent / "models" / "tts"
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
ESPEAK_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/espeak-ng-data.tar.bz2"

VOICES = {
    "hi": "hi/hi_IN/pratham/medium/hi_IN-pratham-medium",
    "te": "te/te_IN/maya/medium/te_IN-maya-medium",
    "ml": "ml/ml_IN/meera/medium/ml_IN-meera-medium",
    "mr": "mr/mr_IN/google/medium/mr_IN-google-medium",
    "bn": "bn/bn_BD/google/medium/bn_BD-google-medium",
    "ur": "ur/ur_PK/fasih/medium/ur_PK-fasih-medium",
    "en": "en/en_US/lessac/medium/en_US-lessac-medium",
}


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)


def convert(lang: str, stem: str) -> None:
    folder = ROOT / lang
    folder.mkdir(parents=True, exist_ok=True)
    raw_model = folder / "raw.onnx"
    config_path = folder / "config.json"
    download(f"{HF}/{stem}.onnx", raw_model)
    download(f"{HF}/{stem}.onnx.json", config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ids = config["phoneme_id_map"]
    with open(folder / "tokens.txt", "w", encoding="utf-8", newline="\n") as tokens:
        for symbol, values in ids.items():
            if len(symbol) == 1:
                tokens.write(f"{symbol} {values[0]}\n")
    model = onnx.load(str(raw_model))
    meta = {
        "model_type": "vits",
        "comment": "piper",
        "language": config.get("language", {}).get("name_english", lang),
        "voice": config["espeak"]["voice"],
        "has_espeak": "1",
        "n_speakers": str(config.get("num_speakers", 1)),
        "sample_rate": str(config["audio"]["sample_rate"]),
    }
    del model.metadata_props[:]
    for key, value in meta.items():
        entry = model.metadata_props.add()
        entry.key = key
        entry.value = value
    onnx.save(model, str(folder / "model.onnx"))
    raw_model.unlink()
    print(f"{lang}: {stem.split('/')[-1]} ready ({meta['voice']}, {meta['sample_rate']} Hz)")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    espeak = ROOT / "espeak-ng-data"
    if not (espeak / "te_dict").exists():
        archive = ROOT / "espeak-ng-data.tar.bz2"
        download(ESPEAK_URL, archive)
        shutil.rmtree(espeak, ignore_errors=True)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(ROOT, filter="data")
        archive.unlink()
    wanted = sys.argv[1:] or list(VOICES)
    for lang in wanted:
        if (ROOT / lang / "model.onnx").exists():
            print(f"{lang}: already present")
            continue
        convert(lang, VOICES[lang])


if __name__ == "__main__":
    main()
