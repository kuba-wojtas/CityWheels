import pytest

from citywheels.tools.policies import load_sections, search_policies, tokenize


def headings(result: dict) -> list[str]:
    return [r["section"] for r in result["results"]]


def test_policies_are_split_into_sections():
    sections = {s.heading: s for s in load_sections()}

    assert len(sections) == 22
    assert sections["Bad weather"].source == "cancellations.md"
    assert "storm warning" in sections["Bad weather"].text
    # H1 titles without their own text are not sections.
    assert "Frequently asked questions" not in sections


@pytest.mark.parametrize(
    "words", [["cancel", "cancelled", "cancelling"], ["year", "years"], ["change", "changed"]]
)
def test_word_forms_share_a_token(words):
    assert len({tokenize(w)[0] for w in words}) == 1


def test_stopwords_are_dropped():
    assert tokenize("What is the price of a bike?") == tokenize("price bike")


@pytest.mark.parametrize(
    "query, expected",
    [
        ("What time do you open on Saturday?", "When are you open?"),
        ("How much is an e-bike for a whole day?", "Bike rental"),
        ("Can my 14-year-old rent an e-bike?", "Are there age limits?"),
        ("I want to cancel my booking", "Cancelling a booking"),
        ("storm warning", "Bad weather"),
        ("What happens if I return the bike late?", "Late return"),
    ],
)
def test_finds_the_right_section(query, expected):
    assert expected in headings(search_policies(query))


def test_rare_word_ranks_its_section_first():
    assert headings(search_policies("dog"))[0] == "Can I take my dog?"


def test_returns_at_most_top_k_with_source_and_text():
    result = search_policies("bike price deposit", top_k=3)

    assert result["status"] == "ok"
    assert len(result["results"]) == 3
    for r in result["results"]:
        assert r["source"].endswith(".md")
        assert r["text"]


@pytest.mark.parametrize("query", ["What is the capital of Australia?", "", "the a is"])
def test_off_topic_or_empty_query_has_no_match(query):
    assert search_policies(query) == {"status": "no_match", "query": query}
