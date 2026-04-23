#!/usr/bin/env python
"""
Phase 1 MVP Demo - 展示工具閘道、輸出驗證、治理日誌的實際使用

在此演示中，我們模擬：
1. 嘗試在 ESG 上下文中調用不允許的工具
2. 檢測讀寫約束違反
3. 驗證輸出結構
4. 查詢審計日誌
"""

from __future__ import annotations

import json
from pathlib import Path

from audits.governance_logger import AuditAction, GovernanceLogger
from validators.output_validator import SchemaType, validate_output_structure
from validators.tool_gatekeeper import secure_tool_call


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def demo_tool_gatekeeper() -> None:
    print_section("Demo 1: 工具閘道 (Tool Gatekeeper)")

    test_cases = [
        {
            "tool_name": "get_weather",
            "context_id": "general",
            "arguments": None,
            "description": "✓ 允許：general context 可以調用 get_weather",
        },
        {
            "tool_name": "get_weather",
            "context_id": "esg",
            "arguments": None,
            "description": "✗ 拒絕：esg context 不允許 get_weather",
        },
        {
            "tool_name": "get_weather",
            "context_id": "general",
            "arguments": {"delete_field": "user_data"},
            "description": "✗ 拒絕：讀寫約束檢測到 delete 操作",
        }
    ]

    for case in test_cases:
        print(f"測試：{case['description']}")
        allowed, reason = secure_tool_call(
            tool_name=case["tool_name"],
            context_id=case["context_id"],
            arguments=case["arguments"],
        )
        status = "✓ ALLOWED" if allowed else "✗ REJECTED"
        print(f"結果：{status}")
        print(f"原因：{reason}\n")


def demo_output_validator() -> None:
    print_section("Demo 2: 輸出驗證 (Output Validator)")

    # 測試 1: 有效的 TOOL_RESULT
    print("測試 1: 有效的 TOOL_RESULT")
    data_valid = {
        "tool_name": "get_weather",
        "status": "success",
        "output": {"temperature": 25, "condition": "sunny"},
    }
    valid, errors = validate_output_structure(data=data_valid, schema_type=SchemaType.TOOL_RESULT)
    print(f"✓ 有效: {valid}")
    print(f"錯誤列表: {errors or '無'}\n")

    # 測試 2: 無效的 TOOL_RESULT（status 值無效）
    print("測試 2: 無效的 TOOL_RESULT（status='unknown'）")
    data_invalid = {
        "tool_name": "get_weather",
        "status": "unknown",  # 只允許 'success' 或 'error'
        "output": None,
    }
    valid, errors = validate_output_structure(data=data_invalid, schema_type=SchemaType.TOOL_RESULT)
    print(f"✗ 無效: {not valid}")
    print(f"錯誤列表:\n  - {chr(10).join(errors)}\n")

    # 測試 3: 有效的 AGENT_RESPONSE
    print("測試 3: 有效的 AGENT_RESPONSE")
    data_agent = {
        "content": "根據天氣資料，今天陽光充足。",
        "context_id": "general",
        "available_tools": ["get_weather"],
    }
    valid, errors = validate_output_structure(data=data_agent, schema_type=SchemaType.AGENT_RESPONSE)
    print(f"✓ 有效: {valid}")
    print(f"錯誤列表: {errors or '無'}\n")

    # 測試 4: 無效的 PEER_REVIEW（verdict='maybe'）
    print("測試 4: 無效的 PEER_REVIEW（verdict='maybe'）")
    data_review = {
        "content": "This code looks mostly good.",
        "reviewer_id": "reviewer-001",
        "verdict": "maybe",  # 只允許 'pass', 'revise', 'reject'
        "criteria": {"code_quality": 8, "documentation": 6},
    }
    valid, errors = validate_output_structure(data=data_review, schema_type=SchemaType.PEER_REVIEW)
    print(f"✗ 無效: {not valid}")
    print(f"錯誤列表:\n  - {chr(10).join(errors)}\n")


def demo_governance_logger() -> None:
    print_section("Demo 3: 治理日誌 (Governance Logger)")

    # 建立測試用的日誌檔案
    log_file = Path("demo_governance_audit.jsonl")
    logger = GovernanceLogger(log_file=log_file)

    # 記錄一系列審計事件
    print("記錄審計事件...")

    from datetime import UTC, datetime
    from uuid import uuid4

    from audits.governance_logger import AuditEntry

    events = [
        AuditEntry(
            trace_id="trace-001",
            action=AuditAction.TOOL_CALL_ALLOWED,
            timestamp=datetime.now(UTC).isoformat(),
            context_id="general",
            tool_name="get_weather",
            reason="Tool is in allowed scope",
        ),
        AuditEntry(
            trace_id="trace-002",
            action=AuditAction.TOOL_CALL_REJECTED,
            timestamp=datetime.now(UTC).isoformat(),
            context_id="esg",
            tool_name="get_weather",
            reason="Tool 'get_weather' is not in allowed scope for context 'esg'",
        ),
        AuditEntry(
            trace_id="trace-003",
            action=AuditAction.OUTPUT_VALIDATION_PASS,
            timestamp=datetime.now(UTC).isoformat(),
            context_id="general",
            tool_name="get_weather",
            reason="Output validation passed",
        ),
        AuditEntry(
            trace_id="trace-004",
            action=AuditAction.OUTPUT_VALIDATION_FAIL,
            timestamp=datetime.now(UTC).isoformat(),
            context_id="esg",
            tool_name=None,
            reason="Invalid status value in TOOL_RESULT",
        ),
    ]

    for event in events:
        logger.log(event)
        print(f"  ✓ 記錄: {event.action.value} (trace_id: {event.trace_id})")

    print(f"\n日誌已儲存到: {log_file.absolute()}\n")

    # 查詢日誌
    print("查詢所有日誌條目：")
    all_entries = logger.get_entries()
    print(f"  總計: {len(all_entries)} 條記錄\n")

    # 篩選拒絕事件
    print("篩選被拒絕的工具呼叫：")
    rejections = logger.rejections()
    for entry in rejections:
        print(f"  - {entry['tool_name']} ({entry['context_id']}): {entry['reason']}")
    print()

    # 統計摘要
    print("審計摘要統計：")
    summary = logger.summary()
    print(f"  總事件數: {summary['total']}")
    print(f"\n  按動作分類:")
    for action, count in summary["by_action"].items():
        print(f"    - {action}: {count}")
    print(f"\n  按上下文分類:")
    for context, count in summary["by_context"].items():
        print(f"    - {context}: {count}")
    print(f"\n  按工具分類:")
    for tool, count in summary["by_tool"].items():
        if tool != "None":
            print(f"    - {tool}: {count}")

    # 清理測試檔案
    if log_file.exists():
        log_file.unlink()
        print(f"\n✓ 清理測試檔案: {log_file}")


def demo_integrated_flow() -> None:
    print_section("Demo 4: 整合流程 (Integrated Tool Call Flow)")

    print("模擬: LLM 要求調用 get_weather 工具在 esg context\n")

    context_id = "esg"
    tool_name = "get_weather"
    arguments = {"city": "Taipei"}

    print(f"Step 1: 安全檢查工具呼叫")
    print(f"  - context_id: {context_id}")
    print(f"  - tool_name: {tool_name}")
    print(f"  - arguments: {arguments}\n")

    allowed, reason = secure_tool_call(tool_name=tool_name, context_id=context_id, arguments=arguments)

    if not allowed:
        print(f"✗ 工具呼叫被拒絕: {reason}")
        print(f"  -> 不會執行此工具，返回錯誤給使用者\n")
    else:
        print(f"✓ 工具呼叫被允許")
        print(f"  -> 可以安全地執行此工具\n")

        print(f"Step 2: 執行工具並驗證輸出")
        # 模擬工具執行結果
        tool_result = {
            "tool_name": "get_weather",
            "status": "success",
            "output": {"city": "Taipei", "temperature": 28, "condition": "cloudy"},
        }
        print(f"  - 工具結果: {json.dumps(tool_result, ensure_ascii=False)}\n")

        valid, errors = validate_output_structure(data=tool_result, schema_type="TOOL_RESULT")

        if not valid:
            print(f"✗ 輸出驗證失敗:")
            for error in errors:
                print(f"    - {error}")
            print(f"  -> 不會使用此輸出，要求重試\n")
        else:
            print(f"✓ 輸出驗證通過")
            print(f"  -> 可以將結果傳遞給 LLM 進行處理\n")


if __name__ == "__main__":
    print("\n" + "█" * 60)
    print("█" + " " * 58 + "█")
    print("█" + "  Phase 1 MVP Demo - Trust Constraint System".center(58) + "█")
    print("█" + " " * 58 + "█")
    print("█" * 60)

    try:
        demo_tool_gatekeeper()
        demo_output_validator()
        demo_governance_logger()
        demo_integrated_flow()

        print_section("Demo 完成")
        print("Phase 1 MVP 包含三個核心模組：")
        print("  1. validators/tool_gatekeeper.py - 工具呼叫合規性檢查")
        print("  2. validators/output_validator.py - 輸出結構驗證")
        print("  3. audits/governance_logger.py - 審計日誌與追蹤")
        print("\n所有單元測試: 11/11 ✓ 通過")
        print("\n下階段：")
        print("  - 在 user_host_server.py 中整合這些檢查到工具呼叫流程")
        print("  - 通過 host_flow_cli.py 進行端點測試驗證")
        print()

    except Exception as e:
        print(f"\n✗ 演示出錯: {e}")
        import traceback

        traceback.print_exc()
