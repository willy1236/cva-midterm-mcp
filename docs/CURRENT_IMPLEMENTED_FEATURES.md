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

### 1.2 Policy / Context（模組 1）

- `config.yaml` 定義目前的 context 與政策內容。
- `config.yaml` 支援全域 `resource_limits`（token、模型呼叫次數、工具次數、工具頻率、總延遲毫秒）。
- 目前有 `general`、`esg`、`code_dev` 三個 context。
- 每個 context 包含 `identity`、`system_prompt`、`absolute_rules` 與 `tool_scope`，也可選擇覆寫 `resource_limits`。
- `host/policies/config_loader.py` 負責從 repository root 讀取設定並回傳對應 profile。
- `host/server.py` 會根據 session 的 `context_id` 套用對應的 system prompt。

### 1.3 Tool Governance（模組 4）

- `host/validators/tool_gatekeeper.py` 實作 `secure_tool_call()`。
- 會檢查工具是否在 context 的允許清單中。
- 會在 `read-only` 模式下檢測參數是否含有寫入或修改意圖。
- 若 `context_id` 不存在，工具呼叫會被拒絕。
- `host/server.py` 在每次工具呼叫前都會先走治理檢查。

### 1.4 Output Validation（模組 2）

- `host/validators/output_validator.py` 實作 `validate_output_structure()`。
- 目前支援四種 schema：`TOOL_RESULT`、`AGENT_RESPONSE`、`PEER_REVIEW`、`AUDIT_REPORT`。
- `TOOL_RESULT` 用於驗證 MCP 工具執行結果。
- `AGENT_RESPONSE` 用於驗證助理輸出，現行格式以 `answer` + `sources` 為主，也保留對舊欄位 `content` 的相容。
- `PEER_REVIEW` 與 `AUDIT_REPORT` 則對應後續可擴充的治理資料格式。

### 1.5 Citation Verification（模組 3）

- `host/server.py` 的系統提示已明確要求模型使用 `[citation:1]` 格式標記回答中的引用。
- `parse_structured_assistant_output()` 會解析最終模型輸出，提取 `answer` 和 `sources` 欄位。
- 結構化輸出格式為 `{"answer": "...", "sources": [{"source_id": "...", "tool_name": "..."}]}`。
- `host/server.py` 在 `/chat` 流程最後階段對 `AGENT_RESPONSE` 進行結構驗證，確保 answer 與 sources 完整。
- `host/audits/governance_logger.py` 已支援記錄 `CITATION_VERIFICATION_PASS`、`CITATION_VERIFICATION_PARTIAL`、`CITATION_VERIFICATION_FAIL` 三種引用驗證結果。
- 完整的引用驗證邏輯（對比主張與來源、判定可追溯性）留待後續實作。

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

## 2. 使用者 Client 層

- `client/cli.py` 提供互動式 CLI，用來操作 host server、建立 session 與送出聊天訊息。
- CLI 主要扮演使用者端操作介面，透過 HTTP 呼叫 host server 完成健康檢查、session 管理與聊天。
- CLI 目前支援 `health`、`session/start`、`sessions`、`session/context`、`chat`、`session/{id}`、本地狀態查看，以及手動設定 `session_id` / `base_url`。

## 3. MCP Server 層

- `mcpServer/app.py` 定義 FastMCP server 與目前已註冊的工具。
- 目前可用的 MCP 工具是 `get_weather()`，用來驗證端到端工具呼叫流程。
- `mcpServer/response.py` 提供結構化回應 envelope，包含 `SuccessResponse`、`ErrorResponse`、`build_success()` 與 `build_error()`。

## 4. OpenAI / Tool Execution 流程

- `host/server.py` 會先向 MCP server 讀取工具清單，再轉成 OpenAI function tools 格式。
- 對話流程支援多輪工具呼叫，模型可先決定要用哪些工具，再由系統執行並回填結果。
- 工具執行後會再經過輸出結構驗證，避免無效結果直接進入對話。
- 最終模型輸出會經過結構化解析，整理成 `assistant_response = {answer, sources}`，並再做 `AGENT_RESPONSE` schema 驗證。
- 若工具呼叫或輸出驗證失敗，系統會回填政策違規或驗證失敗訊息，而不是直接中斷整個對話。
- 若 token、工具次數、工具頻率或總延遲超過 `resource_limits`，流程會觸發熔斷並回傳終止訊息。

## 5. 測試覆蓋

- `tests/test_phase1_mvp.py` 已覆蓋工具守門、輸出驗證與治理稽核。
- 測試重點包含允許 / 拒絕工具呼叫、schema 驗證結果，以及稽核摘要與拒絕查詢。
- `tests/test_resource_circuit_breaker.py` 已覆蓋 token 超限、工具頻率超限、延遲超限與 profile 門檻覆寫。
- `tests/test_citation_verifier.py` 目前保留 citation verifier 相關測試案例檔。

## 6. 實作對應文件

- 若要快速對照程式碼，可先看：
  - `host/server.py`
  - `host/session.py`
  - `host/validators/tool_gatekeeper.py`
  - `host/validators/output_validator.py`
  - `host/validators/resource_circuit_breaker.py`
  - `host/audits/governance_logger.py`
  - `host/policies/config_loader.py`
  - `mcpServer/app.py`
  - `mcpServer/response.py`
  - `client/cli.py`