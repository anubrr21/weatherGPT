import asyncio
import json
import sys
import time

import httpx

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
API = ARGS[0] if ARGS else "http://127.0.0.1:8000"
PACE = next((float(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--pace=")), 0.0)

SCRIPTS = {
    "hi": (0x0900, 0x097F), "mr": (0x0900, 0x097F), "bn": (0x0980, 0x09FF), "as": (0x0980, 0x09FF),
    "pa": (0x0A00, 0x0A7F), "gu": (0x0A80, 0x0AFF), "or": (0x0B00, 0x0B7F), "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F), "ur": (0x0600, 0x06FF),
    "en": (0x0041, 0x007A),
}

CASES = [
    ("en", "Will it rain in Guntur tomorrow?"),
    ("hi", "कल गुंटूर में बारिश होगी क्या?"),
    ("bn", "আগামীকাল কলকাতায় বৃষ্টি হবে কি?"),
    ("te", "రేపు విజయవాడలో వర్షం పడుతుందా?"),
    ("ta", "நாளை சென்னையில் மழை பெய்யுமா?"),
    ("mr", "उद्या पुण्यात पाऊस पडेल का?"),
    ("gu", "કાલે અમદાવાદમાં વરસાદ પડશે?"),
    ("kn", "ನಾಳೆ ಬೆಂಗಳೂರಿನಲ್ಲಿ ಮಳೆ ಬರುತ್ತದೆಯೇ?"),
    ("ml", "നാളെ കൊച്ചിയിൽ മഴ പെയ്യുമോ?"),
    ("or", "କାଲି ଭୁବନେଶ୍ୱରରେ ବର୍ଷା ହେବ କି?"),
    ("pa", "ਕੱਲ੍ਹ ਲੁਧਿਆਣਾ ਵਿੱਚ ਮੀਂਹ ਪਵੇਗਾ?"),
    ("as", "কাইলৈ গুৱাহাটীত বৰষুণ হ'বনে?"),
    ("ur", "کیا کل لکھنؤ میں بارش ہوگی؟"),
    ("hi", "मैं तेनाली के पास धान उगाता हूँ। कीटनाशक कब छिड़कूँ?"),
    ("te", "కాకినాడ నుండి ఈరోజు పడవలు సముద్రంలోకి వెళ్లవచ్చా?"),
]


def script_share(text: str, lang: str) -> float:
    lo, hi = SCRIPTS[lang]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if lo <= ord(c) <= hi) / len(letters)


async def run_case(client: httpx.AsyncClient, lang: str, question: str) -> dict:
    start = time.perf_counter()
    first = None
    text = ""
    tools_used = []
    provider = None
    errors = []
    async with client.stream("POST", f"{API}/api/chat", json={"message": question, "language": lang, "lat": 16.51, "lon": 80.52}) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if event["type"] == "delta":
                first = first or time.perf_counter() - start
                text += event["text"]
            elif event["type"] == "status":
                tools_used.append(event["tool"])
            elif event["type"] == "provider":
                provider = event["label"]
            elif event["type"] == "reset":
                text = ""
            elif event["type"] == "error":
                errors.append(event["text"])
    return {
        "lang": lang,
        "question": question,
        "first_token_s": round(first or 0, 2),
        "total_s": round(time.perf_counter() - start, 2),
        "tools": tools_used,
        "provider": provider,
        "script_share": round(script_share(text, lang), 2),
        "errors": errors,
        "answer": text,
    }


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        health = (await client.get(f"{API}/api/health")).json()
        if not health.get("llm"):
            print("LLM is not enabled: set GEMINI_API_KEY and/or GROQ_API_KEY in backend/.env and restart the API.")
            return
        results = []
        for i, (lang, question) in enumerate(CASES):
            if i and PACE:
                await asyncio.sleep(PACE)
            result = await run_case(client, lang, question)
            results.append(result)
            ok = result["tools"] and result["script_share"] >= 0.6 and not result["errors"]
            print(f"{'PASS' if ok else 'FAIL'} {lang} first={result['first_token_s']}s total={result['total_s']}s script={result['script_share']} tools={result['tools']} via={result['provider']} {result['errors'][:1]}")
        firsts = sorted(r["first_token_s"] for r in results)
        totals = sorted(r["total_s"] for r in results)
        print(f"\nfirst token p50={firsts[len(firsts) // 2]}s  total p50={totals[len(totals) // 2]}s p95={totals[int(len(totals) * 0.95) - 1]}s")
        with open("eval_languages_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("Full answers written to eval_languages_results.json")


asyncio.run(main())
