# 目前已實作功能整理

以下內容依 MCP 架構分層整理目前已完成的功能，聚焦在已存在的元件與入口，不包含尚未完成的規劃項目。

## 1. Host 層（框架主體）

- `main.py` 啟動整體 host 服務與本機 MCP server。
- `host/server.py` 提供對外 HTTP API，負責接收 session、chat 與健康檢查請求。
- `host/server.py` 的 `/chat` 流程會把使用者訊息送入 OpenAI，支援工具呼叫後，回傳結構化的 `assistant_response`。
- Host 層內還包含以下子模組：
  - `host/session.py`：Session / State 管理。
  - `host/policies/config_loader.py`：Policy / Context 載入。
  - `host/validators/tool_gatekeeper.py`：Tool Governance。
  - `host/validators/output_validator.py`：Output Validation。
  - `host/validators/resource_circuit_breaker.py`：Resource / Cost Circuit Breaker。
  - `host/audits/governance_logger.py`：Audit / Logging。

### 1.1 Session / State

- `host/session.py` 定義 `SessionStore` 與 session 相關 request model。
- 會話資料會持久化到 `host_sessions.json`。
- 每筆 session 會保存 `session_id`、`context_id`、`created_at`、`updated_at` 與 `messages`。
- 目前支援建立會話、查詢會話、列出會話、切換 context 與追加訊息。

### 1.2 Context（模組 1）

- `config.yaml` 定義目前的 context 與政策內容。
- `config.yaml` 支援全域 `resource_limits` (模組 7)，以及動態政策 (模組 6)。
- 每個 context 包含 `identity`、`system_prompt`、`absolute_rules` 與 `tool_scope`，也可選擇覆寫 `resource_limits`。
- `host/policies/config_loader.py` 負責從 repository root 讀取設定並回傳對應 profile。
- `host/server.py` 會根據 session 的 `context_id` 套用對應的 system prompt。

### 1.3 Output Validation（模組 2）

- `host/validators/output_validator.py` 實作 `validate_output_structure()`。
- 目前支援四種 schema：`TOOL_RESULT`、`AGENT_RESPONSE`、`PEER_REVIEW`、`AUDIT_REPORT`。
- `TOOL_RESULT` 用於驗證 MCP 工具執行結果。
- `AGENT_RESPONSE` 用於驗證助理輸出，現行格式以 `answer` + `sources` 為主，也保留對舊欄位 `content` 的相容。
- `PEER_REVIEW` 與 `AUDIT_REPORT` 則對應後續可擴充的治理資料格式。

### 1.4 Citation Verification（模組 3）

- `host/server.py` 的系統提示已明確要求模型使用 `[citation:1]` 格式標記回答中的引用。
- `parse_structured_assistant_output()` 會解析最終模型輸出，提取 `answer` 和 `sources` 欄位。
- `host/server.py` 在 `/chat` 流程最後階段對 `AGENT_RESPONSE` 進行結構驗證，確保 answer 與 sources 完整。
- 初步完成針對MCP Tool的引用檢查，完整的引用驗證邏輯（對比外部主張與來源、判定可追溯性）留待後續實作。

### 1.5 Tool Governance（模組 4）

- `host/validators/tool_gatekeeper.py` 實作 `secure_tool_call()`。
- 會檢查工具是否在 context 的允許清單中。
- 會在 `read-only` 模式下檢測參數是否含有寫入或修改意圖。
- 若 `context_id` 不存在，工具呼叫會被拒絕。
- `host/server.py` 在每次工具呼叫前都會先走治理檢查。


### 1.6 Audit / Logging

- `host/audits/governance_logger.py` 提供 `GovernanceLogger`。
- 目前記錄的動作類型包括 `TOOL_CALL_ALLOWED`、`TOOL_CALL_REJECTED`、`OUTPUT_VALIDATION_PASS`、`OUTPUT_VALIDATION_FAIL`、`CITATION_VERIFICATION_PASS`、`CITATION_VERIFICATION_PARTIAL`、`CITATION_VERIFICATION_FAIL`、`CIRCUIT_BREAKER_TRIGGERED` 與 `POLICY_VIOLATION`。
- 稽核資料以 JSONL 寫入 `logs/governance_audit.jsonl`。
- 支援查詢全部紀錄、過濾拒絕紀錄與輸出統計摘要。
- 每筆紀錄包含 `trace_id`、`action`、`timestamp`、`context_id`、`tool_name`、`reason` 與 `details`。

### 1.7 Resource / Cost Circuit Breaker（模組 7）

- `host/validators/resource_circuit_breaker.py` 提供 `ResourceBudget`、`ResourceCircuitBreaker` 與 `ResourceLimitExceeded`。
- 熔斷監控指標包含：`total_tokens`、`model_calls`、`tool_calls`、`tool_calls_by_name` 與 `elapsed_ms`。
- `host/server.py` 在每輪模型回應與工具呼叫過程中都會檢查門檻，超限時中止本輪並回傳終止原因。
- 熔斷觸發時會寫入 `CIRCUIT_BREAKER_TRIGGERED` 審計事件，`details` 會帶當下資源指標。
- 延遲單位為毫秒（ms），欄位為 `max_total_latency_ms`。

### 1.8 Content Safety / Dynamic Policy（模組 6）

此模組負責對模型產出的文本進行三層式安全分類，並根據 context 的政策決定是否允許、修改或阻擋輸出；同時與引用驗證與稽核模組整合，形成對外輸出的治理閉環。

- 主要檔案與職責：
  - `host/validators/content_classifier.py`：內容分類器（規則 + 關鍵詞 + 簡單相似度），回傳 `ClassificationResult`（包含 `classification`, `risk_score`, `content_types`, `blocking_reasons`, `confidence`）。
  - `host/policies/policy_enforcer.py`：政策執行器，根據 context profile 的 policy（位於 `config.yaml` 的 `contexts.<id>.policy`）做允許/阻擋/修改決策，並回傳對應的 `audit_action` 與 `modified_text`（若需加入免責聲明）。
  - `host/validators/citation_verifier.py`：引用驗證工具（Module 3），可檢查主張與來源的對應性並回報 VERIFIED/UNVERIFIED/REJECTED，用於強化知識可追溯性。
  - `host/audits/governance_logger.py`：稽核擴充：新增 `CONTENT_CLASSIFICATION`、`CONTENT_POLICY_APPLIED`、`CONTENT_BLOCKED_BY_POLICY`、`CONTENT_MODIFIED_BY_POLICY` 等事件。
  - `host/server.py`：在對話回覆生成後（step 12.5）插入分類→政策→引用驗證流程，依結果決定是否阻擋或在回覆前加入免責聲明，並記錄對應審計事件。

- 設定位置：
  - 將政策資料（policy defaults 與 context 覆寫）存放於 `config.yaml`：
    - 全域預設：`policy_defaults`（risk 門檻、content_type_policy、requires_disclaimer 等）
    - 各 context 可在 `contexts.<id>.policy` 覆寫（例如 `general` / `esg` / `code_dev`）。
  - `host/policies/config_loader.py` 會合併 `policy_defaults` 與 `contexts.<id>.policy`，並把結果放入 context profile 回傳給 runtime 使用。

## 2. 使用者 Client 層

- `client/cli.py` 提供互動式 CLI，用來操作 host server、建立 session 與送出聊天訊息。
- CLI 主要扮演使用者端操作介面，透過 HTTP 呼叫 host server 完成健康檢查、session 管理與聊天。
- CLI 目前支援 `health`、`session/start`、`sessions`、`session/context`、`chat`、`session/{id}`、本地狀態查看，以及手動設定 `session_id` / `base_url`。

## 3. MCP Server 層

- `mcpServer/app.py` 定義 FastMCP server 與目前已註冊的工具。
- 目前可用的 MCP 工具是 `get_weather()`，用來驗證端到端工具呼叫流程。
- `mcpServer/response.py` 提供結構化回應 envelope，包含 `SuccessResponse`、`ErrorResponse`、`build_success()` 與 `build_error()`。

## 4. OpenAI / Tool Execution 流程

- 於每次執行單輪對話時，`host/server.py` 會透過 `fastmcp.Client(MCP_SERVER_URL).list_tools()` 即時載入 MCP 可用工具，並由 `mcp_tools_to_openai_tools()` 轉為 OpenAI 函式呼叫（function-like）描述。
- 使用 OpenAI 的函式呼叫模式：透過 `call_openai_chat()` 對 `OpenAI.chat.completions.create(...)` 發出請求（包含 `tools`、`tool_choice="auto"` 與 `temperature=0`），模型可能回傳 `tool_calls`。
- 系統支援多輪工具呼叫循環：當模型發出 `tool_calls` 時，server 會先將助理的工具呼叫意圖記錄到對話（含 `tool_call.id` 與參數），再逐一執行對應 MCP 工具（`mcp_client.call_tool()`）。
- 在執行工具前會以 `secure_tool_call()` 做治理檢查；不允許的呼叫會被封鎖並回填一個 policy error 給模型以繼續後續流程（不直接中斷對話）。
- 工具執行結果會用 `format_tool_result()` 格式化（包含 `[工具來源 ID: ...]` 標記），並以 `validate_output_structure(..., SchemaType.TOOL_RESULT)` 驗證工具輸出結構；若驗證失敗，會回填 `output_validation_failed` 的 tool 訊息給模型。
- 在模型不再要求工具後，最終回覆會由 `parse_structured_assistant_output()` 解析為 `{"answer": ..., "sources": [...]}`，接著執行內容分類（`classify_content()`）與政策套用（`enforce_policy()`）。
- 若政策判定為拒絕（blocked），`/chat` 流程會回傳一個被政策阻擋的結構化回覆；若政策要求修改（例如加入免責聲明），會將 `modified_text` 串接到最終 `answer` 前。
- 最後對整體回覆再做一次 `validate_output_structure(..., SchemaType.AGENT_RESPONSE)` 驗證，並把驗證結果寫入稽核日誌。
- 資源與成本監控：`ResourceCircuitBreaker` 監控指標包含 `total_tokens`、`model_calls`、`tool_calls`、`tool_calls_by_name` 與經過時間（elapsed ms）；若超過 `resource_limits`（例如 token、工具頻率或總延遲），會丟出 `ResourceLimitExceeded`，記錄 `CIRCUIT_BREAKER_TRIGGERED` 審計事件，並返回終止訊息給呼叫端。
- 本機 MCP server 支援自動啟動（由 `lifespan` 在背景 process 啟動 `mcp.run()` 當 `AUTO_START_LOCAL_MCP` 為 true），`wait_until_mcp_ready()` 會確認 MCP 可以呼叫 `list_tools()` 後才繼續。

## 5. 測試覆蓋

- 單元與整合測試位於 `tests/`：主要測試檔案包括
  - `tests/test_phase1_mvp.py`：驗證 `secure_tool_call()`、`validate_output_structure()` 與 `GovernanceLogger` 等核心治理邏輯。
  - `tests/test_resource_circuit_breaker.py`：驗證 `ResourceCircuitBreaker` 在 token、工具頻率與延遲超限場景會正確拋出 `ResourceLimitExceeded`，以及 `build_resource_budget()` 會優先採用 profile 的限額設定。
  - `tests/test_module6_integration.py`：Module 6 的端到端整合測試（分類 → 政策 → 阻擋/修改 → 審計），以 `pytest.mark.asyncio` 執行非同步流程驗證。
  - `tests/test_content_classifier.py`、`tests/test_policy_enforcer.py`、`tests/test_citation_verifier.py`：分別覆蓋內容分類、政策執行器與引用驗證的預期行為。
- 測試策略：單元測試覆蓋治理與驗證邏輯，整合測試模擬分類→政策→稽核的完整流程；MCP 工具端的簡易整合可透過 `mcpServer.app.mcp`（`get_weather`）在本地做驗證或使用 `host_flow_cli.py` 進行端到端呼叫測試。

## 6. 實作對應文件
 - 若要快速對照程式碼，可先看：
   - `host/server.py`
   - `host/session.py`
   - `host/validators/tool_gatekeeper.py`
   - `host/validators/output_validator.py`
   - `host/validators/resource_circuit_breaker.py`
   - `host/audits/governance_logger.py`
   - `host/validators/content_classifier.py`
   - `host/validators/citation_verifier.py`
   - `host/policies/config_loader.py`
   - `host/policies/policy_enforcer.py`
   - `mcpServer/app.py`
   - `mcpServer/response.py`
   - `client/cli.py`
   - `config.yaml`（上下文與政策預設）
 