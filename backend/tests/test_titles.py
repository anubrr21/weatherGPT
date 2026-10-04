from app.services.agent import clean_title


def test_plain_title_is_kept():
    assert clean_title("Rain in Amaravati tomorrow") == "Rain in Amaravati tomorrow"


def test_quotes_label_and_punctuation_are_removed():
    assert clean_title('Title: "spraying window this evening."') == "Spraying window this evening"
    assert clean_title("**Chennai commute flooding**\n\nextra line") == "Chennai commute flooding"


def test_indian_script_title_is_kept():
    assert clean_title("कल अमरावती में बारिश।") == "कल अमरावती में बारिश"


def test_bad_titles_are_rejected():
    assert clean_title("") is None
    assert clean_title("I'm sorry, I cannot help with that") is None
    assert clean_title("word " * 12) is None
    assert clean_title("x" * 80) is None
