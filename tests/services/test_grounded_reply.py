from __future__ import annotations

import pytest

from ecommerce_cs_agent.services.grounded_reply import compose_grounded_reply


def context_fixture() -> dict:
    return {
        "products": [
            {
                "external_product_id": "product-spray",
                "title": "宠物免洗除臭喷雾145ml",
                "price": 75,
                "attributes": {"activity_min": "75.00", "stock_total": 4, "status_text": "在售"},
            },
            {
                "external_product_id": "product-bowl",
                "title": "食品级防打翻狗碗",
                "price": 125,
                "attributes": {"activity_min": "125.00", "stock_total": 120, "status_text": "在售"},
            },
            {
                "external_product_id": "product-offline",
                "title": "白毛猫狗香波",
                "price": 471,
                "attributes": {"stock_total": 10, "status_text": "已下架"},
            },
        ],
        "orders": [
            {
                "external_order_id": "pdd-order-a1",
                "items": [{"external_product_id": "product-spray"}],
                "raw_payload": {"display_order_ref": "******************2213", "status_text": "已收货"},
            }
        ],
        "logistics": [
            {
                "external_order_id": "pdd-order-a1",
                "status": "已收货",
                "carrier": "顺丰速运",
                "tracking_no": "**********0156",
            }
        ],
    }


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("product-spray 现在多少钱？", "75"),
        ("product-spray 还有库存吗？", "库存"),
        ("product-offline 还在售吗？", "已下架"),
        ("订单尾号2213用什么快递？", "顺丰"),
        ("订单尾号2213现在到哪一步了？", "已收货"),
    ],
)
def test_compose_grounded_reply_answers_current_intent(message: str, expected: str) -> None:
    outcome = compose_grounded_reply(message=message, history=[], context=context_fixture())

    assert expected in outcome.reply_text
    assert not outcome.reply_text.lstrip().startswith(("{", "["))


def test_comparison_mentions_only_two_selected_products() -> None:
    outcome = compose_grounded_reply(
        message="product-spray 和 product-bowl 哪个活动价低？",
        history=[],
        context=context_fixture(),
    )

    assert "宠物免洗除臭喷雾" in outcome.reply_text
    assert "食品级防打翻狗碗" in outcome.reply_text
    assert "白毛猫狗香波" not in outcome.reply_text
    assert outcome.referenced_entity_ids == ("product-spray", "product-bowl")


def test_history_resolves_previous_and_current_product_references() -> None:
    history = [
        {"sender_type": "buyer", "content": "product-spray 和 product-bowl 哪个活动价低？"},
        {"sender_type": "assistant", "content": "喷雾活动价更低。"},
    ]

    previous = compose_grounded_reply(message="前一个库存多少？", history=history, context=context_fixture())
    latter = compose_grounded_reply(message="后一个呢？", history=history, context=context_fixture())

    assert "4" in previous.reply_text
    assert "120" in latter.reply_text
    assert previous.referenced_entity_ids == ("product-spray",)
    assert latter.referenced_entity_ids == ("product-bowl",)


def test_order_suffix_selects_one_order_and_links_its_product() -> None:
    outcome = compose_grounded_reply(
        message="订单尾号2213买的什么？",
        history=[],
        context=context_fixture(),
    )

    assert "宠物免洗除臭喷雾" in outcome.reply_text
    assert "食品级防打翻狗碗" not in outcome.reply_text
    assert outcome.referenced_entity_ids == ("pdd-order-a1", "product-spray")
