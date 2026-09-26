import pytest
from weekly_summary import select_relevant_articles


def make_article(link, title, domain_scores, combined_score):
    return {
        "link": link,
        "title": title,
        "domain_scores": domain_scores,
        "combined_score": combined_score,
    }


def test_select_per_domain_and_fill():
    articles = [
        make_article("a", "A", {"architecture": 9, "regulation": 0, "ai": 0}, 9),
        make_article("b", "B", {"architecture": 8, "regulation": 0, "ai": 0}, 8),
        make_article("c", "C", {"architecture": 2, "regulation": 9, "ai": 0}, 9),
        make_article("d", "D", {"architecture": 1, "regulation": 8, "ai": 0}, 8),
        make_article("e", "E", {"architecture": 0, "regulation": 0, "ai": 9}, 9),
        make_article("f", "F", {"architecture": 0, "regulation": 0, "ai": 8}, 8),
    ]

    selected = select_relevant_articles(articles, threshold=6, per_domain_top=1, max_combined=3)
    links = [a["link"] for a in selected]
    assert len(selected) == 3
    # Should include top from each domain (a,c,e)
    assert set(links) == {"a", "c", "e"}


def test_deduplication_by_link():
    # an article strong in multiple domains should only appear once
    articles = [
        make_article("x", "X", {"architecture": 9, "regulation": 9, "ai": 0}, 18),
        make_article("y", "Y", {"architecture": 8, "regulation": 0, "ai": 8}, 16),
        make_article("z", "Z", {"architecture": 0, "regulation": 7, "ai": 7}, 14),
    ]

    selected = select_relevant_articles(articles, threshold=5, per_domain_top=2, max_combined=3)
    links = [a["link"] for a in selected]
    assert links.count("x") == 1
    assert len(selected) == 3
    assert len(selected) == 3