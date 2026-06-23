from __future__ import annotations

from ecommerce_cs_agent.services.product_analysis import DeterministicProductDocumentAnalyzer


def test_deterministic_analyzer_extracts_labeled_product_fields_without_regex() -> None:
    analyzer = DeterministicProductDocumentAnalyzer()
    content = "\n".join(
            [
                "  商品名称 ：  棉质短袖  ",
                "外部商品 ID: sku-1001",
                "这个标签名称故意写得非常非常长超过二十四个字符所以不应该被识别: ignored",
                "适用季节：夏季",
            ]
    )

    result = analyzer.analyze(text=content, file_name="manual.txt", mime_type="text/plain")

    assert result["draft_product"]["title"] == "棉质短袖"
    assert result["draft_product"]["external_product_id"] == "sku-1001"
    assert result["draft_product"]["attributes"] == {"适用季节": "夏季"}
