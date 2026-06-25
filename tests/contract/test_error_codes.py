from __future__ import annotations

from pathlib import Path

from ecommerce_cs_agent.api.error_codes import ERROR_CODE_REGISTRY


ROOT = Path(__file__).resolve().parents[2]


def test_error_code_registry_is_unique_and_documented() -> None:
    ids = [entry["id"] for entry in ERROR_CODE_REGISTRY]
    assert len(ids) == len(set(ids))

    docs = (ROOT / "docs" / "error-codes.md").read_text(encoding="utf-8")
    for error_id in ids:
        assert f"| {error_id} |" in docs

    for heading in ["错误编号", "用户可见提示", "触发条件", "排查步骤", "对应代码文件", "函数/位置", "相关接口", "上游错误映射"]:
        assert heading in docs
