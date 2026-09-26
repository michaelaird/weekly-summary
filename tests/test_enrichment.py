from weekly_summary import enrich_selected_articles


def make_article(link, title, summary="S"):
    return {"link": link, "title": title, "summary": summary}


def test_enrich_preserves_order_and_fallback(monkeypatch):
    calls = []

    def fake_fetch(url, fallback):
        calls.append(url)
        if url == "bad":
            raise Exception("blocked")
        return f"full:{url}"

    monkeypatch.setattr("weekly_summary.fetch_article_content", fake_fetch)

    articles = [make_article("a", "A"), make_article("bad", "B", summary="fallback"), make_article("c", "C")]
    enriched = enrich_selected_articles(articles)

    assert [a["link"] for a in enriched] == ["a", "bad", "c"]
    assert enriched[0]["full_text"] == "full:a"
    assert enriched[1]["full_text"] == "fallback"
    assert enriched[2]["full_text"] == "full:c"
    assert enriched[2]["full_text"] == "full:c"