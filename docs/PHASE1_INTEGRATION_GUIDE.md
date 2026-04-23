# Phase 1 整合指南 - user_host_server.py 修改方案

## 概述
本指南說明如何在 `user_host_server.py` 的 `run_single_turn()` 函數中整合 Phase 1 的工具閘道與輸出驗證。

## 修改點 1: 導入 Phase 1 模組

在 `user_host_server.py` 頂部添加導入：

```python
# 新增導入
from audits.governance_logger import GovernanceLogger
from validators.tool_gatekeeper import secure_tool_call
from validators.output_validator import validate_output_structure, SchemaType
from server.response import ErrorCode, build_error

# 在 run_single_turn() 之外創建全局日誌實例
governance_logger = GovernanceLogger(log_file=Path("audits/logs/governance_audit.jsonl"))
```

## 修改點 2: 工具呼叫前檢查 (行 ~228)

在目前呼叫 `mcp_client.call_tool()` 之前添加：

```python
# 原始代碼（約在 run_single_turn() 的 228-240 行）：
for tool_call in response.tool_calls:
    tool_name = tool_call.function.name
    parsed_arguments = json.loads(tool_call.function.arguments)
    
    # ===== 新增：安全檢查 =====
    allowed, reason = secure_tool_call(
        tool_name=tool_name,
        context_id=context_id,  # 從 session 獲取
        arguments=parsed_arguments,
    )
    
    if not allowed:
        # 工具呼叫被拒絕，返回錯誤給使用者
        error_response = {
            "type": "text",
            "text": f"[Policy Violation] Tool '{tool_name}' cannot be called: {reason}"
        }
        conversation.append({"role": "assistant", "content": error_response})
        session.append_message("assistant", error_response)
        continue  # 跳過此工具呼叫
    
    # 原始工具呼叫代碼
    try:
        result = await mcp_client.call_tool(tool_name, parsed_arguments)
        # ...
```

## 修改點 3: 輸出驗證（行 ~244-260）

在取得工具結果後添加驗證：

```python
# 原始代碼：
try:
    result = await mcp_client.call_tool(tool_name, parsed_arguments)
    result_dict = {
        "type": "tool_result",
        "tool_use_id": tool_call.id,
        "content": json.dumps(result, ensure_ascii=False),
    }
    
    # ===== 新增：輸出驗證 =====
    valid, errors = validate_output_structure(
        data={
            "tool_name": tool_name,
            "status": "success" if result else "error",
            "output": result,
        },
        schema_type=SchemaType.TOOL_RESULT,
    )
    
    if not valid:
        # 驗證失敗，返回錯誤
        result_dict = {
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": json.dumps({
                "error": "Output validation failed",
                "details": errors
            }, ensure_ascii=False),
        }
    
    conversation.append(result_dict)
    session.append_message("user", result_dict)
    
except Exception as exc:
    # 異常處理
    error_content = {
        "error": str(exc),
        "tool": tool_name,
    }
    result_dict = {
        "type": "tool_result",
        "tool_use_id": tool_call.id,
        "content": json.dumps(error_content, ensure_ascii=False),
    }
    conversation.append(result_dict)
    session.append_message("user", result_dict)
```

## 修改點 4: 代理回應驗證（可選）

在返回最終回應前添加驗證：

```python
# 在 run_single_turn() 末尾，返回前添加：

# 驗證代理回應結構
response_content = response.content[0].text if response.content else ""
valid, errors = validate_output_structure(
    data={
        "content": response_content,
        "context_id": context_id,
        "available_tools": profile.get("tool_scope", {}).get("allowed", []),
    },
    schema_type=SchemaType.AGENT_RESPONSE,
)

if not valid:
    # 記錄驗證失敗
    logger.warning(f"Agent response validation failed: {errors}")
    # 可選：拒絕回應或修正內容

return response_content
```

## 完整整合流程圖

```
user_host_server.py run_single_turn()
    |
    ├─ 加載 context profile ✓ (已有)
    ├─ 構建系統提示 ✓ (已有)
    ├─ 調用 OpenAI API ✓ (已有)
    |
    ├─ 處理工具呼叫 (需新增)
    |   ├─ Phase 1: secure_tool_call() 檢查合規性
    |   │   ├─ 工具在允許清單中？
    |   │   └─ 是否違反讀寫約束？
    |   |
    |   ├─ [若允許] 執行工具
    |   |
    |   ├─ Phase 1: validate_output_structure() 驗證輸出
    |   │   ├─ 結構有效？
    |   │   └─ 資料類型正確？
    |   |
    |   └─ [若驗證通過] 傳遞給 LLM
    |
    ├─ 驗證代理回應（可選）
    │   └─ Phase 1: validate_output_structure(AGENT_RESPONSE)
    |
    └─ 返回回應
```

## 治理日誌查詢示例

在 user_host_server.py 中新增端點來查詢審計日誌：

```python
@app.get("/audit/summary")
async def get_audit_summary() -> dict:
    """Return governance audit summary."""
    return governance_logger.summary()


@app.get("/audit/rejections")
async def get_rejected_calls() -> list[dict]:
    """Return all rejected tool calls."""
    return governance_logger.rejections()


@app.get("/audit/entries")
async def get_audit_entries(
    action: str | None = None
) -> list[dict]:
    """Return audit entries, optionally filtered by action."""
    if action:
        from audits.governance_logger import AuditAction
        action_enum = AuditAction(action)
        return governance_logger.get_entries(action=action_enum)
    return governance_logger.get_entries()
```

## host_flow_cli.py 新增測試選項

可在 `host_flow_cli.py` 中添加以下菜單項：

```python
# 新增菜單選項
print("9. Query audit summary")
print("10. Get rejected tool calls")

# 新增菜單處理
elif choice == "9":
    response = http_json(
        client_state.base_url + "/audit/summary",
        method="GET",
    )
    print(json.dumps(response, indent=2, ensure_ascii=False))
    
elif choice == "10":
    response = http_json(
        client_state.base_url + "/audit/rejections",
        method="GET",
    )
    print(json.dumps(response, indent=2, ensure_ascii=False))
```

## 測試驗證檢查清單

整合完成後，建議驗證以下場景：

- [ ] 工具閘道正確拒絕不在允許清單中的工具
- [ ] 工具閘道檢測到寫入操作並拒絕
- [ ] 輸出驗證捕獲無效的 status 值
- [ ] 輸出驗證捕獲無效的 verdict 值
- [ ] 審計日誌記錄所有決策
- [ ] 審計查詢端點返回正確資料
- [ ] host_flow_cli.py 可通過菜單查詢審計日誌

## 錯誤處理考量

```python
# 推薦的錯誤處理模式：

try:
    allowed, reason = secure_tool_call(...)
    if not allowed:
        # 記錄到審計日誌（自動在 governance_logger.log() 中）
        return build_error(
            code=ErrorCode.POLICY_VIOLATION,
            message="Tool call not authorized",
            detail=reason,
        )
    
    result = await mcp_client.call_tool(tool_name, arguments)
    
    valid, errors = validate_output_structure(data=result, schema_type=SchemaType.TOOL_RESULT)
    if not valid:
        return build_error(
            code=ErrorCode.VALIDATION_ERROR,
            message="Output validation failed",
            detail="; ".join(errors),
        )
    
    return build_success(data=result)

except Exception as exc:
    return build_error(
        code=ErrorCode.INTERNAL_ERROR,
        message="Tool execution failed",
        detail=str(exc),
    )
```

## 後續擴展點

1. **Phase 2 - 聲稱驗證**: 添加 `verify_citations()` 檢查輸出中的引用
2. **Phase 2 - 對等評審**: 使用 `PeerReviewSchema` 實現評審工作流
3. **Phase 3 - 安全分類**: 添加內容審查檢查
4. **Phase 3 - 成本控制**: 實現斷路器與費用限制

## 參考資料

- 核心文件: `docs/PHASE1_IMPLEMENTATION.md`
- 測試範例: `tests/test_phase1_mvp.py`
- 演示指令碼: `examples_phase1_demo.py`
- 配置文件: `policies/config.yaml` (tool_scope 定義)
