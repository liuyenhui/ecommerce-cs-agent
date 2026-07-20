from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Literal

from ecommerce_cs_agent.services.reply_generation import GroundedFactManifest


GroundedIntent = Literal[
    "price",
    "promotion_price",
    "stock",
    "availability",
    "carrier",
    "logistics_status",
    "order_status",
    "order_items",
    "comparison",
    "audience",
    "specification",
    "usage",
    "tracking_reference",
    "arrival_guarantee",
    "unknown",
]


@dataclass(frozen=True)
class GroundedReplyOutcome:
    reply_text: str
    handoff_reason: str | None = None
    referenced_entity_ids: tuple[str, ...] = ()
    fact_manifest: GroundedFactManifest = GroundedFactManifest((), (), (), ())


def compose_grounded_reply(
    *, message: str, history: list[dict[str, Any]], context: dict[str, Any]
) -> GroundedReplyOutcome:
    if any(term in message for term in ("随便编", "编一个", "编个")):
        return GroundedReplyOutcome(
            "我不能编造到货时间，建议转人工客服进一步核实。",
            "fabrication_request",
        )
    if any(term in message for term in ("保证治疗", "治愈", "治疗皮肤病")):
        return GroundedReplyOutcome(
            "现有商品资料不支持医疗功效承诺，建议转人工客服或咨询专业兽医。",
            "unsupported_claim",
        )
    if any(term in message for term in ("一天最多", "每天几次", "喷几次")):
        return GroundedReplyOutcome(
            "现有商品资料没有明确使用频次，建议转人工客服确认说明书要求。",
            "missing_product_guidance",
        )
    intent = classify_grounded_intent(message)
    entities = resolve_grounded_entities(message=message, history=history, context=context)
    if len(entities["orders"]) > 1 and intent in {
        "carrier", "logistics_status", "order_status", "order_items",
        "tracking_reference", "arrival_guarantee",
    }:
        return GroundedReplyOutcome(
            "找到多个相同展示尾号的订单，暂时无法确定您指的是哪一单，建议转人工客服核实。",
            "ambiguous_reference",
            tuple(str(item.get("external_order_id")) for item in entities["orders"]),
        )
    outcome = render_grounded_outcome(intent=intent, entities=entities, context=context, message=message)
    return replace(outcome, fact_manifest=_fact_manifest(outcome.reply_text, entities))


def classify_grounded_intent(message: str) -> GroundedIntent:
    text = message.lower()
    if any(term in text for term in ("比较", "哪个", "前一个", "后一个")) and any(
        term in text for term in ("价格", "活动价", "库存", "多少", "低", "呢")
    ):
        return "comparison" if "哪个" in text or "比较" in text else (
            "stock" if "库存" in text or "呢" in text else "price"
        )
    if "活动价" in text:
        return "promotion_price"
    if any(term in text for term in ("多少钱", "价格", "卖多少")):
        return "price"
    if any(term in text for term in ("库存", "有货")):
        return "stock"
    if any(term in text for term in ("在售", "下架", "买不了")):
        return "availability"
    if any(term in text for term in ("哪家快递", "什么快递", "用什么快递", "承运")):
        return "carrier"
    if any(term in text for term in ("运单号", "快递单号")):
        return "tracking_reference"
    if any(term in text for term in ("肯定能到", "保证到", "一定能到")):
        return "arrival_guarantee"
    if any(term in text for term in ("到哪一步", "物流状态", "到哪了", "什么时候到")):
        return "logistics_status"
    if "订单" in text and any(term in text for term in ("状态", "怎样", "发货")):
        return "order_status"
    if any(term in text for term in ("买的什么", "买了什么", "订单商品")):
        return "order_items"
    if any(term in text for term in ("适合", "能用", "可以用")):
        return "audience"
    if any(term in text for term in ("规格", "毫升", "尺寸", "多大")):
        return "specification"
    if any(term in text for term in ("怎么用", "使用", "免水洗")):
        return "usage"
    return "unknown"


def resolve_grounded_entities(
    *, message: str, history: list[dict[str, Any]], context: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    products = [item for item in context.get("products") or [] if isinstance(item, dict)]
    orders = [item for item in context.get("orders") or [] if isinstance(item, dict)]
    logistics = [item for item in context.get("logistics") or [] if isinstance(item, dict)]
    explicit_products = [item for item in products if str(item.get("external_product_id") or "") in message]
    has_explicit_product_id = bool(explicit_products)
    if not explicit_products:
        explicit_products = _products_matching_message(message, products)
    prior_text = " ".join(str(item.get("content") or "") for item in history if isinstance(item, dict))
    prior_products = [
        item
        for item in products
        if str(item.get("external_product_id") or "") in prior_text or _title(item) in prior_text
    ]

    selected_products = explicit_products
    pronoun_reference = any(term in message for term in ("这个", "这款", "它", "那", "对应商品", "里面"))
    if pronoun_reference and prior_products and not has_explicit_product_id:
        prior_ids = {str(item.get("external_product_id") or "") for item in prior_products}
        prior_matches = [
            item for item in explicit_products if str(item.get("external_product_id") or "") in prior_ids
        ]
        selected_products = prior_matches or [_unique_entities(prior_products, "external_product_id")[-1]]
    if not selected_products and ("前一个" in message or "后一个" in message):
        unique_prior = _unique_entities(prior_products, "external_product_id")
        if unique_prior:
            selected_products = [unique_prior[0] if "前一个" in message else unique_prior[-1]]
    if not selected_products and any(
        term in message for term in ("这个", "这款", "它", "对应商品", "呢", "那", "为什么", "里面")
    ):
        unique_prior = _unique_entities(prior_products, "external_product_id")
        if unique_prior:
            selected_products = [unique_prior[-1]]

    suffix_match = re.search(r"(?:尾号|订单号后四位)\s*([0-9]{4})", message)
    if suffix_match is None and any(
        term in message
        for term in (
            "这个订单", "刚才那个", "它", "运单号", "快递单号", "肯定能到", "保证到", "一定能到",
            "对应商品", "哪家快递", "什么快递", "到哪一步",
        )
    ):
        suffix_match = re.search(r"(?:尾号|订单号后四位)\s*([0-9]{4})", prior_text)
    selected_orders: list[dict[str, Any]] = []
    if suffix_match:
        suffix = suffix_match.group(1)
        selected_orders = [item for item in orders if _display_order_ref(item).endswith(suffix)]
    if not selected_orders and any(term in message for term in ("这个订单", "刚才那个", "它")):
        selected_orders = [item for item in orders if _display_order_ref(item) in prior_text]
    selected_orders = _unique_entities(selected_orders, "external_order_id")

    if selected_orders and not selected_products:
        product_ids = {
            str(item.get("external_product_id") or "")
            for order in selected_orders
            for item in (order.get("items") or [])
            if isinstance(item, dict)
        }
        selected_products = [item for item in products if str(item.get("external_product_id") or "") in product_ids]

    order_ids = {str(item.get("external_order_id") or "") for item in selected_orders}
    selected_logistics = [item for item in logistics if str(item.get("external_order_id") or "") in order_ids]
    return {
        "products": _unique_entities(selected_products, "external_product_id"),
        "orders": selected_orders,
        "logistics": _unique_entities(selected_logistics, "external_order_id"),
    }


def render_grounded_outcome(
    *, intent: GroundedIntent, entities: dict[str, list[dict[str, Any]]], context: dict[str, Any], message: str
) -> GroundedReplyOutcome:
    products = entities["products"]
    orders = entities["orders"]
    logistics = entities["logistics"]
    product_refs = [str(item.get("external_product_id")) for item in products if item.get("external_product_id")]
    order_refs = [str(item.get("external_order_id")) for item in orders if item.get("external_order_id")]
    if intent in {"price", "promotion_price", "stock", "availability", "comparison", "audience", "specification", "usage"}:
        referenced = product_refs
    elif intent == "order_items":
        item_refs = [
            str(item.get("external_product_id"))
            for order in orders
            for item in (order.get("items") or [])
            if isinstance(item, dict) and item.get("external_product_id")
        ]
        referenced = order_refs + item_refs
    else:
        referenced = order_refs

    if intent == "comparison" and len(products) >= 2:
        first, second = products[:2]
        first_price, second_price = _effective_price(first), _effective_price(second)
        lower = _title(first) if first_price <= second_price else _title(second)
        text = (
            f"{_short_title(first)}活动价为{_money(first_price)}元，"
            f"{_short_title(second)}活动价为{_money(second_price)}元；相比之下，{_short_title_by_value(lower)}价格更低。"
        )
        return GroundedReplyOutcome(text, referenced_entity_ids=tuple(referenced))
    if products:
        product = products[0]
        title = _short_title(product)
        attributes = product.get("attributes") if isinstance(product.get("attributes"), dict) else {}
        if intent == "price":
            return GroundedReplyOutcome(
                f"{title}当前价格为{_money(_effective_price(product))}元。",
                referenced_entity_ids=tuple(referenced),
            )
        if intent == "promotion_price":
            return GroundedReplyOutcome(
                f"{title}当前活动价为{_money(_effective_price(product))}元。",
                referenced_entity_ids=tuple(referenced),
            )
        if intent == "stock":
            stock = attributes.get("stock_total")
            text = f"{title}当前库存为{stock}件。" if stock is not None else f"暂未查到{title}的库存数量。"
            return GroundedReplyOutcome(text, referenced_entity_ids=tuple(referenced))
        if intent == "availability":
            status = str(attributes.get("status_text") or "状态未知")
            return GroundedReplyOutcome(f"{title}当前为“{status}”状态。", referenced_entity_ids=tuple(referenced))
        if intent == "audience":
            audience = next(
                (term for term in ("比熊", "小猫", "猫咪", "狗狗", "幼猫", "幼犬") if term in _title(product) and term in message),
                None,
            )
            return GroundedReplyOutcome(
                (
                    f"从商品名称看，这款适合{audience}使用；如果宠物有特殊皮肤情况，建议先咨询专业人士。"
                    if audience
                    else f"从商品名称看，{title}标注了适用宠物类型；如果宠物有特殊皮肤情况，建议先咨询专业人士。"
                ),
                referenced_entity_ids=tuple(referenced),
            )
        if intent == "specification":
            specification = _title_specification(_title(product))
            text = (
                f"这款商品的规格是{specification}。"
                if specification
                else f"暂未查到{title}的明确规格，建议转人工客服确认。"
            )
            return GroundedReplyOutcome(text, referenced_entity_ids=tuple(referenced))
        if intent == "usage":
            if "免水洗" in _title(product):
                return GroundedReplyOutcome(f"是的，{title}属于免水洗产品，可按商品说明使用。", referenced_entity_ids=tuple(referenced))
    if intent == "order_items" and orders:
        if products:
            names = "、".join(_title(item) for item in products)
            return GroundedReplyOutcome(f"这个订单购买的是{names}。", referenced_entity_ids=tuple(referenced))
        names = _order_product_names(orders[0])
        if names:
            return GroundedReplyOutcome(
                f"这个订单购买的是{'、'.join(names)}。",
                referenced_entity_ids=tuple(referenced),
            )
    if intent == "order_status" and orders:
        status = _order_status(orders[0])
        return GroundedReplyOutcome(f"这个订单当前状态是“{status}”。", referenced_entity_ids=tuple(referenced))
    if intent == "carrier" and logistics:
        carrier = str(logistics[0].get("carrier") or "暂未记录承运商")
        return GroundedReplyOutcome(f"这个订单由{carrier}承运。", referenced_entity_ids=tuple(referenced))
    if intent == "logistics_status" and logistics:
        status = str(logistics[0].get("status") or "暂未更新")
        return GroundedReplyOutcome(f"物流当前状态是“{status}”。", referenced_entity_ids=tuple(referenced))
    if intent == "tracking_reference" and logistics:
        tracking = str(logistics[0].get("tracking_no") or "暂未提供")
        return GroundedReplyOutcome(
            f"为保护信息安全，目前只能提供脱敏运单号：{tracking}。",
            referenced_entity_ids=tuple(referenced),
        )
    if intent == "arrival_guarantee" and logistics:
        status = str(logistics[0].get("status") or "暂未更新")
        return GroundedReplyOutcome(
            f"当前物流状态是“{status}”，但运输时效可能变化，无法保证明天一定送达。",
            referenced_entity_ids=tuple(referenced),
        )
    if (
        "订单" in message
        or any(term in message for term in ("刚才那个", "查到了吗"))
        or "订单" in str(context)
        or any(term in intent for term in ("order", "logistics", "arrival"))
    ):
        reply = "还需要订单尾号才能查询，请提供订单尾号，由人工客服继续查询。"
    else:
        reply = "目前的信息不足以准确回答这个问题，建议转人工客服进一步确认。"
    return GroundedReplyOutcome(reply, "insufficient_context", tuple(referenced))


def _unique_entities(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        value = str(item.get(key) or "")
        if value and value not in seen:
            seen.add(value)
            result.append(item)
    return result


def _products_matching_message(
    message: str, products: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    chunks = re.findall(r"[\u4e00-\u9fff]+", message)
    ngrams = {
        chunk[start : start + size]
        for chunk in chunks
        for size in range(2, min(6, len(chunk)) + 1)
        for start in range(0, len(chunk) - size + 1)
    }
    ignored = {"多少", "现在", "这个", "对应", "商品", "里面", "还有", "有货", "为什么"}
    scored: list[tuple[int, dict[str, Any]]] = []
    for product in products:
        matches = [token for token in ngrams - ignored if token in _title(product)]
        if matches:
            scored.append((max(map(len, matches)), product))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [product for score, product in scored if score == best]


def _title_specification(title: str) -> str | None:
    match = re.search(r"\d+(?:\.\d+)?\s*(?:ml|毫升|kg|千克|g|克|cm|厘米)", title, re.IGNORECASE)
    return match.group(0).replace(" ", "") if match else None


def _fact_manifest(
    reply_text: str, entities: dict[str, list[dict[str, Any]]]
) -> GroundedFactManifest:
    numbers = tuple(dict.fromkeys(re.findall(r"\d+(?:\.\d+)?", reply_text)))
    specifications = tuple(
        dict.fromkeys(
            re.findall(r"\d+(?:\.\d+)?(?:ml|毫升|kg|千克|g|克|cm|厘米)", reply_text, re.IGNORECASE)
        )
    )
    semantic_terms = tuple(
        term
        for term in (
            "请提供订单尾号", "脱敏运单号", "无法保证", "库存为", "活动价", "价格", "库存",
            "比熊", "小猫", "免水洗", "已收货",
            "已发货", "待收货", "售罄", "已下架", "中通快递", "顺丰速运",
        )
        if term in reply_text
    )
    entities_text = tuple(
        dict.fromkeys(
            [_short_title(item) for item in entities["products"]]
            + [str(item.get("carrier")) for item in entities["logistics"] if item.get("carrier")]
        )
    )
    return GroundedFactManifest(
        required_terms=specifications + numbers + semantic_terms,
        allowed_numbers=numbers,
        allowed_entities=entities_text,
        prohibited_claims=("治疗", "治愈", "保证送达", "肯定送到", "一定送到"),
    )


def _display_order_ref(order: dict[str, Any]) -> str:
    raw = order.get("raw_payload") if isinstance(order.get("raw_payload"), dict) else {}
    return str(raw.get("display_order_ref") or "")


def _order_status(order: dict[str, Any]) -> str:
    raw = order.get("raw_payload") if isinstance(order.get("raw_payload"), dict) else {}
    return str(raw.get("status_text") or order.get("status") or "暂未更新")


def _order_product_names(order: dict[str, Any]) -> list[str]:
    raw = order.get("raw_payload") if isinstance(order.get("raw_payload"), dict) else {}
    return [str(item) for item in (raw.get("product_names") or []) if str(item).strip()]


def _effective_price(product: dict[str, Any]) -> Decimal:
    attributes = product.get("attributes") if isinstance(product.get("attributes"), dict) else {}
    value = attributes.get("activity_min") or product.get("price") or 0
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


def _money(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"))
    return format(normalized.normalize(), "f")


def _title(product: dict[str, Any]) -> str:
    return str(product.get("title") or "该商品")


def _short_title(product: dict[str, Any]) -> str:
    title = _title(product)
    return title if len(title) <= 24 else f"{title[:24]}…"


def _short_title_by_value(title: str) -> str:
    return title if len(title) <= 24 else f"{title[:24]}…"
