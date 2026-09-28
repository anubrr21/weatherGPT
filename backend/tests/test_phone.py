import base64
import hashlib
import hmac

import pytest

from app.services import ivr, phone


def test_indian_numbers_normalise():
    assert phone.normalize_phone("98765 43210") == "+919876543210"
    assert phone.normalize_phone("+91-98765-43210") == "+919876543210"
    assert phone.normalize_phone("09876543210") == "+919876543210"
    with pytest.raises(phone.PhoneError):
        phone.normalize_phone("12345")


def test_sms_segments_follow_gsm7_and_ucs2_rules():
    assert phone.sms_encoding("A" * 160) == ("gsm7", 1)
    assert phone.sms_encoding("A" * 161) == ("gsm7", 2)
    assert phone.sms_encoding("A" * 306) == ("gsm7", 2)
    assert phone.sms_encoding("{" * 80) == ("gsm7", 1)
    assert phone.sms_encoding("क" * 70) == ("ucs2", 1)
    assert phone.sms_encoding("क" * 71) == ("ucs2", 2)
    assert phone.sms_encoding("Tenali 25-34°C") == ("ucs2", 1)


def test_fit_trims_at_sentence_boundaries():
    text = "आज बारिश होगी। " * 30
    fitted = phone.fit(text, 2)
    assert phone.sms_encoding(fitted)[1] <= 2
    assert fitted.endswith("।")


def test_commands_in_english_hindi_and_pin_codes():
    assert phone.parse("WEATHER Tenali") == ("weather", "Tenali")
    assert phone.parse("मौसम गुंटूर") == ("weather", "गुंटूर")
    assert phone.parse("522237") == ("weather", "522237")
    assert phone.parse("join Bahraich") == ("join", "Bahraich")
    assert phone.parse("STOP") == ("stop", "")
    assert phone.parse("हाँ") == ("yes", "")
    assert phone.parse("LANG TE") == ("lang", "TE")
    assert phone.parse("telugu") == ("lang", "telugu")
    assert phone.parse("Will it rain tomorrow in Guntur?")[0] == "ask"


def test_twilio_signature_follows_the_published_algorithm(monkeypatch):
    monkeypatch.setattr(phone, "get_settings", lambda: type("S", (), {"twilio_auth_token": "12345"})())
    url = "https://weathergpt.example.in/api/sms/twilio"
    params = {"From": "+919876543210", "Body": "WEATHER Tenali", "AccountSid": "AC1", "To": "+918000000000"}
    payload = url + "AccountSidAC1BodyWEATHER TenaliFrom+919876543210To+918000000000"
    signature = base64.b64encode(hmac.new(b"12345", payload.encode(), hashlib.sha1).digest()).decode()
    assert phone.valid_twilio_signature(url, params, signature)
    assert not phone.valid_twilio_signature(url, params | {"Body": "STOP"}, signature)
    assert not phone.valid_twilio_signature(url, params, None)


def test_twiml_gathers_digits_and_plays_audio():
    step = {"audio_url": "/api/ivr/audio/abc.wav", "gather": 6, "timeout": 12, "hangup": False}
    xml = ivr.twiml(step, "https://weathergpt.example.in", "https://weathergpt.example.in/api/ivr/twilio")
    assert '<Gather input="dtmf" numDigits="6" timeout="12"' in xml
    assert "<Play>https://weathergpt.example.in/api/ivr/audio/abc.wav</Play>" in xml
    assert "<Hangup/>" in ivr.twiml(step | {"hangup": True}, "https://x", "https://x/a")


def test_translations_are_rejected_when_refused_or_incomplete():
    source = "Press 5 to change your place. Press 9 to change language."
    assert phone.valid_translation(source, "अपनी जगह बदलने के लिए 5 दबाएँ। भाषा बदलने के लिए 9 दबाएँ।", "hi")
    assert phone.valid_translation(source, "अपनी जगह बदलने के लिए ५ दबाएँ। भाषा बदलने के लिए ९ दबाएँ।", "hi")
    assert not phone.valid_translation(source, "अपनी जगह बदलने के लिए 5 दबाएँ।", "hi")
    assert not phone.valid_translation("Please type your 6 digit PIN code.", "I’m sorry, but I can’t help with that.", "hi")
    assert not phone.valid_translation(source, "Press 5 to change your place. Press 9 to change language.", "te")


def test_placeholders_must_survive_translation_and_are_filled():
    source = "Your place is [PLACE], [DISTRICT] district."
    assert phone.valid_translation(source, "మీ ప్రదేశం [PLACE], [DISTRICT] జిల్లా.", "te")
    assert not phone.valid_translation(source, "మీ ప్రదేశం [PLACE] జిల్లా.", "te")
    assert phone._fill(source, {"place": "Tenali", "district": "Guntur"}) == "Your place is Tenali, Guntur district."
