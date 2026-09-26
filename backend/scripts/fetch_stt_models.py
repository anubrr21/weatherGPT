import argparse
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "models" / "stt"
INDIC_FILES = ("preprocessor.onnx", "encoder.onnx", "ctc_decoder.onnx", "vocab.json", "language_masks.json")
WHISPER_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-base.en.tar.bz2"
WHISPER_FILES = {
    "base.en-encoder.int8.onnx": "base.en-encoder.int8.onnx",
    "base.en-decoder.int8.onnx": "base.en-decoder.int8.onnx",
    "base.en-tokens.txt": "base.en-tokens.txt",
}


def indic(source: Path | None) -> None:
    target = ROOT / "indic_conformer"
    if all((target / name).exists() for name in INDIC_FILES):
        print("IndicConformer already installed")
        return
    if source is None or not all((source / name).exists() for name in INDIC_FILES):
        print(
            "IndicConformer needs the exported ONNX bundle (preprocessor, int8 encoder, CTC decoder, vocab, language masks).\n"
            "AI4Bharat's model is gated on Hugging Face, so it cannot be downloaded anonymously. Export it once with\n"
            "iTantra/ml/stt/onnx_export (see its README), then run:\n"
            "  python scripts/fetch_stt_models.py --indic-from <folder with the five files>"
        )
        return
    target.mkdir(parents=True, exist_ok=True)
    for name in INDIC_FILES:
        shutil.copy2(source / name, target / name)
        print(f"copied {name}")


def whisper() -> None:
    target = ROOT / "whisper_en"
    if all((target / name).exists() for name in WHISPER_FILES.values()):
        print("Whisper base.en already installed")
        return
    target.mkdir(parents=True, exist_ok=True)
    archive = ROOT / "whisper-base.en.tar.bz2"
    print(f"downloading {WHISPER_URL}")
    with urllib.request.urlopen(WHISPER_URL) as response, open(archive, "wb") as out:
        shutil.copyfileobj(response, out)
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar.getmembers():
            name = Path(member.name).name
            if name in WHISPER_FILES:
                source = tar.extractfile(member)
                if source:
                    with source, open(target / WHISPER_FILES[name], "wb") as out:
                        shutil.copyfileobj(source, out)
                    print(f"extracted {name}")
    archive.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install the local speech recognition models")
    parser.add_argument("--indic-from", type=Path, help="folder holding the exported IndicConformer ONNX bundle")
    parser.add_argument("--skip-whisper", action="store_true")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    indic(args.indic_from)
    if not args.skip_whisper:
        whisper()
    sys.exit(0)
