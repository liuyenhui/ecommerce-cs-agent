from __future__ import annotations

from typing import Any, Literal, TypedDict


ServiceStage = Literal["pre_sale", "in_sale", "after_sale", "unknown"]
ReasonCode = Literal[
    "purchase_intent",
    "repurchase_intent",
    "awaiting_fulfillment",
    "in_transit_unreceived",
    "delivered_usage",
    "delivered_quality",
    "return_refund",
    "repair_warranty",
    "mixed_intent",
    "insufficient_context",
]


class ServiceStageClassification(TypedDict):
    primary_stage: ServiceStage
    secondary_stages: list[ServiceStage]
    confidence: float
    reason_code: ReasonCode
    evidence_refs: list[str]
    needs_context: list[str]


PRE_SALE_PRODUCT_TERMS = (
    "重量", "功率", "容量", "材质", "尺寸", "颜色", "规格", "参数", "型号", "版本",
    "适合", "适配", "包装", "一盒", "几个", "有货", "库存", "优惠", "区别", "推荐", "白色",
    "weight", "power", "capacity", "material", "size", "color", "model", "version", "stock",
)
PURCHASE_TERMS = ("想买", "要买", "购买", "下单", "再买", "换个新", "推荐", "buy", "purchase")
REPURCHASE_TERMS = ("上次买", "之前用", "以前买", "再买", "复购", "给家人", "换新型号")
IN_SALE_TERMS = (
    "订单", "支付", "付款", "发货", "物流", "快递", "送到", "收到", "未收到", "没收到",
    "取消订单", "改地址", "加个备注", "订单加", "拒收", "自提", "包裹", "只发", "shipment", "delivery",
)
AFTER_USAGE_TERMS = ("安装", "怎么使用", "怎么用", "清洗", "发票", "补开")
AFTER_QUALITY_TERMS = ("坏了", "坏的", "不通电", "少了", "缺少", "型号不对", "有问题", "瑕疵", "破损")
RETURN_TERMS = ("退货", "退款", "换个颜色", "退换")
REPAIR_TERMS = ("保修", "维修", "维修配件")
DELIVERED_TERMS = ("收到后", "已经收到了", "签收后", "收到就是", "货收到了", "已经签收", "收到的", "签收时", "订单完成")
SHIPPING_TERMS = ("发货", "物流", "快递", "送到", "没收到", "未收到", "在路上", "路上", "自提", "包裹", "只发")
TRANSIT_TERMS = ("物流", "快递", "送到", "没收到", "未收到", "在路上", "路上", "自提", "包裹", "只发")

PRE_DELIVERY_STATUSES = {
    "pending_payment", "paid", "processing", "unshipped", "shipped", "in_transit", "out_for_delivery",
}
DELIVERED_STATUSES = {"delivered", "completed", "received", "signed"}


def normalize_order_status(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "待付款": "pending_payment", "已付款": "paid", "待发货": "processing", "已发货": "shipped",
        "运输中": "in_transit", "派送中": "out_for_delivery", "已签收": "delivered", "已完成": "completed",
    }
    return aliases.get(normalized, normalized)


def classify_service_stage(
    *,
    message: str,
    conversation: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> ServiceStageClassification:
    content = str(message or "").strip()
    lowered = content.lower()
    context = context or {}
    orders = _records(context.get("orders"))
    logistics = _records(context.get("logistics"))
    products = _records(context.get("products"))
    rules = _records(context.get("rules"))
    statuses = [normalize_order_status(order.get("status")) for order in orders]
    logistics_statuses = [normalize_order_status(item.get("status")) for item in logistics]
    delivered = any(status in DELIVERED_STATUSES for status in statuses)
    before_delivery = any(status in PRE_DELIVERY_STATUSES for status in (*statuses, *logistics_statuses))

    repurchase = _contains(lowered, REPURCHASE_TERMS) and _contains(lowered, PURCHASE_TERMS)
    pre_product = _contains(lowered, PRE_SALE_PRODUCT_TERMS)
    purchase = repurchase or _contains(lowered, PURCHASE_TERMS)
    after_usage = _contains(lowered, AFTER_USAGE_TERMS)
    after_quality = _contains(lowered, AFTER_QUALITY_TERMS)
    returns = _contains(lowered, RETURN_TERMS)
    repair = _contains(lowered, REPAIR_TERMS)
    explicit_delivered = _contains(lowered, DELIVERED_TERMS)
    after = after_usage or after_quality or returns or repair
    in_sale = _contains(lowered, IN_SALE_TERMS) and not explicit_delivered
    vague_order = "订单有问题" in lowered or "订单怎么售后" in lowered
    vague_package = "包裹有点问题" in lowered
    delivery_ambiguous = "不知道有没有签收" in lowered
    if (delivered or explicit_delivered) and after:
        pre_product = False
    if repair and "维修配件" in lowered and not _contains(lowered, ("推荐", "新的", "再买")):
        purchase = False
    if vague_order or vague_package or delivery_ambiguous:
        in_sale = False
        after = False

    stages: list[ServiceStage] = []
    if purchase or pre_product:
        stages.append("pre_sale")
    if in_sale and (before_delivery or not delivered):
        stages.append("in_sale")
    if after and (delivered or explicit_delivered or repair or returns):
        stages.append("after_sale")
    stages = list(dict.fromkeys(stages))

    if len(stages) > 1:
        primary = _mixed_primary(content, stages)
        secondary = [stage for stage in stages if stage != primary]
        reason: ReasonCode = "mixed_intent"
    elif stages:
        primary = stages[0]
        secondary = []
        reason = _reason_for(
            primary,
            repurchase=repurchase,
            before_delivery=before_delivery,
            shipping=_contains(lowered, TRANSIT_TERMS) and (before_delivery or not orders),
            after_usage=after_usage,
            after_quality=after_quality,
            returns=returns,
            repair=repair,
        )
    else:
        primary = "unknown"
        secondary = []
        reason = "insufficient_context"

    needs = _needed_context(
        content=lowered,
        primary=primary,
        stages=stages,
        orders=orders,
        logistics=logistics,
        products=products,
        rules=rules,
        pre_product=pre_product,
        after_usage=after_usage,
        returns=returns,
        repair=repair,
        statuses=statuses,
    )
    return {
        "primary_stage": primary,
        "secondary_stages": secondary,
        "confidence": 0.45 if primary == "unknown" else (0.82 if secondary else 0.92),
        "reason_code": reason,
        "evidence_refs": _evidence_refs(orders, logistics, products, rules),
        "needs_context": needs,
    }


def _mixed_primary(content: str, stages: list[ServiceStage]) -> ServiceStage:
    if "in_sale" in stages:
        return "in_sale"
    positions: list[tuple[int, ServiceStage]] = []
    for stage, terms in (("pre_sale", (*PURCHASE_TERMS, "推荐")), ("after_sale", (*AFTER_USAGE_TERMS, *AFTER_QUALITY_TERMS, *RETURN_TERMS, *REPAIR_TERMS))):
        found = [content.find(term) for term in terms if term in content]
        if found:
            positions.append((min(found), stage))
    if "这次" in content and "pre_sale" in stages:
        return "pre_sale"
    return min(positions)[1] if positions else stages[0]


def _reason_for(
    stage: ServiceStage,
    *,
    repurchase: bool,
    before_delivery: bool,
    shipping: bool,
    after_usage: bool,
    after_quality: bool,
    returns: bool,
    repair: bool,
) -> ReasonCode:
    if stage == "pre_sale":
        return "repurchase_intent" if repurchase else "purchase_intent"
    if stage == "in_sale":
        return "in_transit_unreceived" if shipping else "awaiting_fulfillment"
    if repair:
        return "repair_warranty"
    if returns:
        return "return_refund"
    if after_quality:
        return "delivered_quality"
    if after_usage:
        return "delivered_usage"
    return "insufficient_context"


def _needed_context(
    *,
    content: str,
    primary: ServiceStage,
    stages: list[ServiceStage],
    orders: list[dict[str, Any]],
    logistics: list[dict[str, Any]],
    products: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    pre_product: bool,
    after_usage: bool,
    returns: bool,
    repair: bool,
    statuses: list[str],
) -> list[str]:
    needs: list[str] = []
    vague_order = "订单有问题" in content or "订单怎么售后" in content
    vague_package = "包裹有点问题" in content
    delivery_ambiguous = "不知道有没有签收" in content
    old_product = "以前买的那个" in content
    if ("in_sale" in stages or vague_order or vague_package) and not orders:
        needs.append("orders")
    shipping = _contains(content, SHIPPING_TERMS)
    action_only = _contains(content, ("改地址", "加个备注", "订单加", "取消订单"))
    if (shipping and not logistics and not action_only) or (orders and not any(statuses) and "售后" in content) or delivery_ambiguous:
        needs.append("logistics")
    usage_needs_product = after_usage and not _contains(content, ("发票", "补开"))
    purchase_needs_product = primary == "pre_sale" and _contains(content, ("型号", "推荐", "哪款"))
    if ((pre_product and primary == "pre_sale") or purchase_needs_product or usage_needs_product or old_product) and not products:
        needs.append("products")
    if (returns or repair or "怎么售后" in content or "怎么退" in content) and not rules:
        needs.append("rules")
    return list(dict.fromkeys(needs))


def _evidence_refs(*groups: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    fields = ("external_order_id", "logistics_id", "external_product_id", "rule_id", "id")
    for group in groups:
        for item in group:
            value = next((str(item.get(field)) for field in fields if item.get(field)), "")
            if value:
                refs.append(value)
    return refs


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _contains(content: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in content for term in terms)
