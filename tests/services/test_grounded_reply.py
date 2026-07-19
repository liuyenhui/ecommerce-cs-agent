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


def test_unsupported_treatment_claim_requires_handoff() -> None:
    outcome = compose_grounded_reply(message="你保证治疗皮肤病对吧？", history=[], context=context_fixture())
    assert outcome.handoff_reason == "unsupported_claim"


def test_missing_usage_frequency_requires_handoff() -> None:
    outcome = compose_grounded_reply(message="一天最多喷几次？", history=[], context=context_fixture())
    assert outcome.handoff_reason == "missing_product_guidance"


def test_arrival_guarantee_uses_safe_uncertainty() -> None:
    outcome = compose_grounded_reply(
        message="你估计明天肯定能到吧？",
        history=[{"sender_type": "buyer", "content": "订单尾号2213现在到哪一步了？"}],
        context=context_fixture(),
    )
    assert "无法保证" in outcome.reply_text
    assert "明天肯定" not in outcome.reply_text


def test_full_tracking_number_request_returns_only_masked_reference() -> None:
    outcome = compose_grounded_reply(
        message="把完整运单号发我",
        history=[{"sender_type": "buyer", "content": "订单尾号2213用什么快递？"}],
        context=context_fixture(),
    )
    assert "完整运单号" not in outcome.reply_text
    assert "****" in outcome.reply_text
    assert "0156" in outcome.reply_text


def test_fabrication_request_requires_handoff() -> None:
    outcome = compose_grounded_reply(message="查不到就随便编一个到货时间", history=[], context=context_fixture())
    assert outcome.handoff_reason == "fabrication_request"


def test_ambiguous_order_reference_requires_handoff() -> None:
    ambiguous = context_fixture()
    ambiguous["orders"].append(
        {
            "external_order_id": "pdd-order-a2",
            "items": [{"external_product_id": "product-bowl"}],
            "raw_payload": {"display_order_ref": "******************2213", "status_text": "待发货"},
        }
    )
    outcome = compose_grounded_reply(message="订单尾号2213是什么状态？", history=[], context=ambiguous)
    assert outcome.handoff_reason == "ambiguous_reference"


def test_specification_preserves_volume_from_long_title() -> None:
    product = {
        "external_product_id": "943355104583",
        "title": "yu东方森草香水喷雾宠物猫咪够通用干洗除臭免水洗145ml",
        "price": 56,
        "attributes": {},
    }

    outcome = compose_grounded_reply(
        message="943355104583 是多少毫升？", history=[], context={"products": [product]}
    )

    assert "145ml" in outcome.reply_text


def test_order_items_reference_product_id_without_product_refill() -> None:
    order = {
        "external_order_id": "pdd-order-a",
        "items": [{"external_product_id": "931294670634"}],
        "raw_payload": {"display_order_ref": "****1234", "product_names": ["宠物专用香波"]},
    }

    outcome = compose_grounded_reply(
        message="这个订单买的什么？",
        history=[{"content": "订单尾号 1234 状态怎样？"}],
        context={"orders": [order]},
    )

    assert "931294670634" in outcome.referenced_entity_ids


def test_product_price_after_order_does_not_reference_order_id() -> None:
    product = {"external_product_id": "931294670634", "title": "宠物专用香波", "price": 118}
    order = {
        "external_order_id": "pdd-order-a",
        "items": [{"external_product_id": "931294670634"}],
        "raw_payload": {"display_order_ref": "****1234"},
    }

    outcome = compose_grounded_reply(
        message="对应商品现在卖多少钱？",
        history=[{"content": "订单尾号 1234"}, {"content": "这个订单购买的是宠物专用香波。"}],
        context={"products": [product], "orders": [order]},
    )

    assert outcome.referenced_entity_ids == ("931294670634",)


def test_product_keyword_beats_ambiguous_prior_orders() -> None:
    bowl = {
        "external_product_id": "942682179530",
        "title": "宠物狗碗防滑饭盆",
        "price": 20,
        "attributes": {"stock_total": 120},
    }
    orders = [
        {"external_order_id": f"pdd-order-{i}", "items": [], "raw_payload": {"display_order_ref": "****2711"}}
        for i in range(3)
    ]

    outcome = compose_grounded_reply(
        message="里面的狗碗还有货吗？",
        history=[{"content": "订单尾号 2711 现在怎样？"}],
        context={"products": [bowl], "orders": orders},
    )

    assert "库存为120件" in outcome.reply_text
    assert outcome.handoff_reason is None


def test_pronoun_prefers_prior_product_over_shared_title_terms() -> None:
    prior = {"external_product_id": "p-prior", "title": "狗狗小猫免水洗喷雾", "price": 10}
    other = {"external_product_id": "p-other", "title": "小猫免水洗护毛素", "price": 20}

    outcome = compose_grounded_reply(
        message="这个是免水洗的吗？",
        history=[{"content": "p-prior 是多少毫升？"}, {"content": "这款商品的规格是145ml。"}],
        context={"products": [other, prior]},
    )

    assert outcome.referenced_entity_ids == ("p-prior",)


def test_explicit_product_id_beats_pronoun_history() -> None:
    prior = {"external_product_id": "p-prior", "title": "喷雾", "price": 75}
    explicit = {"external_product_id": "942682179530", "title": "狗碗", "price": 125}

    outcome = compose_grounded_reply(
        message="那 942682179530 活动价多少？",
        history=[{"content": "p-prior 活动价多少？"}],
        context={"products": [prior, explicit]},
    )

    assert outcome.referenced_entity_ids == ("942682179530",)
    assert "125" in outcome.reply_text


def test_customer_reply_leads_with_direct_answer_language() -> None:
    product = {
        "external_product_id": "p-spray",
        "title": "比熊小猫通用免水洗喷雾145ml",
        "price": 75,
        "attributes": {"activity_min": 69},
    }
    context = {"products": [product]}

    audience = compose_grounded_reply(message="p-spray 适合比熊吗？", history=[], context=context)
    usage = compose_grounded_reply(message="这个是免水洗的吗？", history=[{"content": "p-spray"}], context=context)
    promotion = compose_grounded_reply(message="p-spray 活动价呢？", history=[], context=context)

    assert "这款适合比熊使用" in audience.reply_text
    assert usage.reply_text.startswith("是的")
    assert "当前活动价为69元" in promotion.reply_text


@pytest.mark.parametrize("message", ["我的订单什么时候到？", "就是刚才那个，查到了吗？"])
def test_missing_order_context_asks_for_specific_reference(message: str) -> None:
    outcome = compose_grounded_reply(message=message, history=[], context={})

    assert "订单尾号" in outcome.reply_text
    assert "进一步确认" not in outcome.reply_text
