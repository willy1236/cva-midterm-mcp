# Phase 1 MVP 實裝總結

## 概述
Phase 1 實現了三個核心模組，用於在 MCP server 層面對工具調用與輸出進行合規性檢查：

1. **工具閘道** (`validators/tool_gatekeeper.py`) - 檢查工具呼叫授權與讀寫約束
2. **輸出驗證** (`validators/output_validator.py`) - 驗證輸出結構與格式
3. **治理稽核** (`audits/governance_logger.py`) - 記錄所有決策與審計追蹤

## 實裝清單

### 1. 工具閘道 (`validators/tool_gatekeeper.py`)
```python
secure_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    context_id: str = "general"
) -> tuple[bool, str]
```

**功能：**
- 驗證工具是否在該上下文允許清單中
- 檢測讀寫約束違反（在 `arguments` 中偵測 `delete`, `create`, `write`, `update` 等關鍵字）
- 返回 `(allowed: bool, reason: str)`

**檢查流程：**
1. 讀取該 context_id 的 profile
2. 檢查 tool_name 是否在 `tool_scope.allowed[]` 中
3. 若 mode 為 read-only，則掃描 arguments 中的寫入關鍵字
4. 返回檢查結果

### 2. 輸出驗證 (`validators/output_validator.py`)
```python
validate_output_structure(
    data: Any,
    schema_type: SchemaType | str
) -> tuple[bool, list[str]]
```

**支援的結構類型：**
- `TOOL_RESULT` - 工具執行結果 (tool_name, status, output)
- `AGENT_RESPONSE` - 代理回應 (content, context_id, available_tools)
- `PEER_REVIEW` - 對等評審 (content, reviewer_id, verdict, criteria)
- `AUDIT_REPORT` - 稽核報告 (action, trace_id, context_id, timestamp)

**檢查流程：**
1. 根據 schema_type 選擇 Pydantic model
2. 對資料進行模型驗證
3. 返回 `(valid: bool, errors: list[str])`

### 3. 治理稽核 (`audits/governance_logger.py`)
```python
class GovernanceLogger:
    def log(entry: AuditEntry) -> None
    def get_entries(action: AuditAction | None = None) -> list[dict]
    def summary() -> dict
    def rejections() -> list[dict]
```

**稽核動作類型：**
- `TOOL_CALL_ALLOWED` - 工具呼叫獲批
- `TOOL_CALL_REJECTED` - 工具呼叫被拒絕
- `OUTPUT_VALIDATION_PASS` - 輸出驗證通過
- `OUTPUT_VALIDATION_FAIL` - 輸出驗證失敗
- `POLICY_VIOLATION` - 政策違反

**日誌存儲：**
- JSONL 格式（每行一條記錄）
- 儲存位置：`audits/logs/governance_audit.jsonl`
- 每條記錄包含：trace_id、action、timestamp、context_id、tool_name、reason、details

## MCP Server 集成

在 `server/app.py` 中添加了兩個新的 FastMCP tool endpoints：

### 1. `secure_tool_call_endpoint`
```python
secure_tool_call_endpoint(
    tool_name: str,
    context_id: str = "general",
    arguments: dict[str, Any] | None = None
) -> SuccessResponse | ErrorResponse
```

**流程：**
1. 調用 `secure_tool_call()` 進行檢查
2. 記錄到治理日誌
3. 返回合規檢查結果（trace_id、允許/拒絕原因）

### 2. `validate_output_structure_endpoint`
```python
validate_output_structure_endpoint(
    data: dict | list[dict],
    schema_type: str
) -> SuccessResponse | ErrorResponse
```

**流程：**
1. 調用 `validate_output_structure()` 進行驗證
2. 記錄到治理日誌
3. 返回驗證結果（有效/無效、錯誤列表）

## 測試覆蓋

11 個單元測試，全數通過（測試檔案：`tests/test_phase1_mvp.py`）：

### 工具閘道測試 (4 項)
- ✓ 允許的工具在正確上下文
- ✓ 不允許的工具被拒絕
- ✓ 讀寫約束檢測
- ✓ 未知上下文拒絕

### 輸出驗證測試 (4 項)
- ✓ TOOL_RESULT 有效結構
- ✓ 無效狀態值拒絕
- ✓ AGENT_RESPONSE 有效結構
- ✓ 無效評審裁決拒絕

### 治理稽核測試 (3 項)
- ✓ 日誌記錄與檢索
- ✓ 統計摘要計算
- ✓ 按動作篩選

## 使用流程示例

### 場景 1: 檢查工具呼叫合規性

```python
# 在 user_host_server.py 的 run_single_turn() 中，
# 工具呼叫前調用此函數：

allowed, reason = secure_tool_call(
    tool_name="get_weather",
    context_id=session.context_id,
    arguments=arguments
)

if not allowed:
    # 拒絕工具呼叫，返回錯誤給使用者
    return ErrorResponse(...)
else:
    # 允許工具呼叫，調用 MCP tool
    result = await mcp_client.call_tool(tool_name, arguments)
```

### 場景 2: 驗證代理輸出

```python
# 在收到 LLM 回應後，驗證結構：

valid, errors = validate_output_structure(
    data={
        "content": llm_response,
        "context_id": session.context_id,
        "available_tools": allowed_tools
    },
    schema_type=SchemaType.AGENT_RESPONSE
)

if not valid:
    return ErrorResponse(errors=errors)
```

### 場景 3: 查詢審計日誌

```python
# 檢查被拒絕的工具呼叫：

rejections = governance_logger.rejections()
for entry in rejections:
    print(f"Rejected: {entry['tool_name']} - {entry['reason']}")

# 獲取統計摘要：
summary = governance_logger.summary()
print(f"Total audited actions: {summary['total']}")
print(f"Rejections by context: {summary['by_context']}")
```

## 檔案清單

**新增檔案：**
- `audits/governance_logger.py` (134 行) - 治理稽核模組
- `validators/output_validator.py` (106 行) - 輸出驗證模組
- `validators/tool_gatekeeper.py` (48 行) - 工具閘道模組
- `tests/test_phase1_mvp.py` (230 行) - 完整測試套件

**修改檔案：**
- `server/app.py` - 添加兩個新的 FastMCP tool endpoints + 導入
- `audits/logs/` - 新建目錄，用於存儲日誌檔案

## 下階段（Phase 2）入口點

Phase 1 完成後，可進行下列擴展：

1. **聲稱驗證** - 實現 `verify_citations()` 函數，檢查輸出引用來源匹配
2. **對等評審** - 整合 `PeerReviewSchema` 與評審引擎
3. **內容安全分類器** - 針對有害內容的審查
4. **成本控制** - 實現斷路器與費用跟蹤

## 集成檢查清單

- [x] 工具閘道實裝 (tool_gatekeeper.py)
- [x] 輸出驗證實裝 (output_validator.py)
- [x] 治理日誌實裝 (governance_logger.py)
- [x] MCP server endpoints 整合
- [x] 單元測試 (11/11 通過)
- [x] 日誌目錄創建
- [ ] host_flow_cli.py 端點測試 (待手動驗證)
- [ ] 與 run_single_turn() 工具呼叫流程整合 (待後續實裝)
