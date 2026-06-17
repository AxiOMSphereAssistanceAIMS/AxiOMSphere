from ops.docgen.universal_overlay.recommendation_pool import build_recommendation_pool


def test_recommendation_pool_dedupes_and_flags_conflicts() -> None:
    pool = build_recommendation_pool(
        document_name="AIMS Registry Report",
        document_type="technical_report",
        axi_recommendations=[
            "Add a standards register for this document.",
            "Add a standards register for this document.",
            "Remove the standards register for this document.",
        ],
        profile_recommendations=[
            "Add a standards register for this document.",
        ],
        source_records=[
            {
                "source_title": "ISO 690:2021",
                "source_url": "https://www.iso.org/standard/72642.html",
                "page_refs": ["11"],
                "excerpt": "Guidelines for bibliographic references.",
            }
        ],
        body_citations=["ISO 690"],
    )

    assert pool["document_name"] == "AIMS Registry Report"
    assert pool["document_type"] == "technical_report"
    assert pool["item_count"] >= 2
    assert pool["duplicates_removed"] >= 1
    assert pool["status"] == "REVIEW"
    assert pool["conflict_pool"]
    assert pool["conflict_pool"][0]["document_name"] == "AIMS Registry Report"
