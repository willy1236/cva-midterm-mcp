# 代理式 AI 信任限制框架：系統開發計畫

## 1. 計畫定位
本開發計畫將研究文件中的七大限制模組，轉換為可實作、可測試、可上線的工程路線。開發主軸是先建立最小可用治理閉環，再逐步擴充到多代理審查與成本熔斷，避免一次做完導致風險失控。

## 2. 開發目標
1. 將固定限制 Prompt 與設定檔落地為可配置、可版本化的政策系統。
2. 在 MCP 架構內實作工具閘道、輸出驗證、引用查核與審查機制。
3. 建立可量化的評估儀表，追蹤越界率、幻覺率、格式合格率、工具誤用率與成本。
4. 形成可重複部署的最小產品（MVP）與擴充版（v1）。

## 3. 現況與差距
### 3.1 目前已有
1. 最小 MCP Server 與工具註冊機制。
2. Agent loop（模型呼叫 + 工具呼叫）。
3. 基本工具呼叫測試。

### 3.2 尚未實作
1. 政策注入與情境切換（Identity / Constraint Config）。
2. 工具權限閘道（Tool Scope 檢查與阻斷）。
3. 結構化輸出驗證（Schema 驗證與拒絕策略）。
4. 引用查核（Claims-Sources 一致性檢驗）。
5. 多代理審查流與治理稽核日誌。
6. 安全分類器與成本熔斷控制。

## 4. 目標架構（工程視角）
1. Policy Layer：載入 `config.yaml`、注入 `get_agent_profile()`、政策版本管理。
2. Guardrail Layer：`secure_tool_call()`、`validate_output_structure()`、拒絕策略。
3. Grounding Layer：`verify_citations()`、來源定位與未證實標記。
4. Review Layer：`submit_for_peer_review()`、審查規則、審查結果整併。
5. Governance Layer：`log_governance_audit()`、審計欄位、追蹤 ID。
6. Runtime Control：成本監控、速率限制、熔斷與降級處理。

## 5. 分階段開發里程碑
### Phase 0（第 1 週）：專案基線整理
目標：把目前原型整理成可擴充結構。

工作項目：
1. 重構目錄結構（server、policies、validators、reviews、audits、tests）。
2. 建立 `config.yaml` 與情境範本（ESG、Code Dev、General）。
3. 定義統一錯誤碼與回應格式。

驗收標準：
1. 能啟動 MCP server 並載入 config。
2. 所有 API 回應可統一為 JSON 結構。

### Phase 1（第 2-3 週）：核心防線 MVP
目標：先完成最小治理閉環（模組 1/2/4）。

工作項目：
1. 實作 `get_agent_profile(context_id)`。
2. 實作 `fetch_constraint_config()`。
3. 實作 `secure_tool_call(tool_name, arguments)`：
   - Tool Scope 檢查
   - 唯讀工具寫入阻斷
4. 實作 `validate_output_structure(data, schema_type)`：
   - Pydantic schema 驗證
   - 不合法輸出拒絕與回報

驗收標準：
1. 未授權工具調用可被阻斷且寫入稽核日誌。
2. 錯誤輸出格式無法進入下游流程。
3. ESG/Code Dev 兩情境可切換且邊界不同。

### Phase 2（第 4-5 週）：可信內容驗證
目標：補上知識接地與審查流程（模組 3/5）。

工作項目：
1. 實作 `verify_citations(claims, sources)`：
   - 證據匹配規則
   - 未證實標記
2. 實作 `submit_for_peer_review(content, criteria)`：
   - Reviewer 任務模板
   - 審查結論（pass/revise/reject）
3. 實作審查結果整併策略（主代理 + 審查代理）。

驗收標準：
1. 無來源主張會被標示為未證實或退件。
2. 未通過審查內容不可作為授權輸出。
3. 審查結論可追溯到完整輸入與判準。

### Phase 3（第 6 週）：治理與穩定化
目標：補齊安全分類、審計、熔斷（模組 6/7）。

工作項目：
1. 接入內容安全分類器（政策等級切換）。
2. 實作 `log_governance_audit(action, reason)`，記錄完整決策軌跡。
3. 建立成本與延遲監控：token、工具次數、總耗時。
4. 實作熔斷策略：超閾值中止、降級回應、告警。

驗收標準：
1. 命中高風險政策時可阻擋輸出。
2. 每次決策都可追蹤 `trace_id` 與拒絕理由。
3. 成本超限時能正確中止並回報。

### Phase 4（第 7-8 週）：整合測試與發布
目標：完成端到端測試、文件與版本發布。

工作項目：
1. 建立三類測試集：正常、邊界、攻擊。
2. 執行對照實驗（Baseline / Prompt-only / Full Framework）。
3. 產出效能與可信度報告。
4. 撰寫部署手冊與操作手冊。

驗收標準：
1. 指標可重現且有明顯改善趨勢。
2. 文件足以支援新成員獨立部署與驗證。
3. 釋出 v1.0 標籤與變更紀錄。

## 6. 工作分解（WBS）
1. 架構與政策
- 配置模型、情境模板、版本控管策略。
2. 核心服務
- MCP endpoints、guardrail middleware、錯誤處理。
3. 驗證與審查
- schema 驗證、citation matcher、peer review engine。
4. 治理與監控
- audit log、metrics collector、circuit breaker。
5. 測試與品質
- 單元測試、整合測試、攻防測試、回歸測試。
6. 文件與運維
- API spec、runbook、部署設定、故障排除手冊。

## 7. 品質保證與測試策略
1. 單元測試：每個 endpoint 的輸入/輸出與拒絕條件。
2. 整合測試：agent loop 與 MCP server 全流程。
3. 安全測試：prompt injection、工具越權、引用偽造。
4. 壓力測試：高並發與長鏈推理場景。
5. 回歸測試：政策調整後的行為一致性。

## 8. 指標儀表與監控
1. 可信指標：越界率、幻覺率、引用可追溯率。
2. 品質指標：格式合格率、審查通過率、重審次數。
3. 系統指標：平均延遲、峰值延遲、token 成本、工具呼叫次數。
4. 風險指標：熔斷觸發次數、政策衝突次數、拒絕率。

## 9. 風險與應對
1. 需求膨脹：以 phase gate 管理，不跨階段堆功能。
2. 準確率與成本衝突：先定成本上限，再優化策略。
3. 審查回路過長：限制重審次數，必要時轉人工審核。
4. 政策衝突：設定優先級矩陣與衝突解決規則。
5. 假陽性過高：保留人工覆核與白名單調整機制。

## 10. 團隊角色建議
1. Tech Lead：架構、模組邊界、風險決策。
2. Backend Engineer：MCP endpoints、middleware、資料流程。
3. AI Engineer：Prompt policy、審查模板、引用查核規則。
4. QA/SRE：測試框架、監控與故障演練。

## 11. 交付清單
1. 可執行 MCP 治理服務（v1.0）。
2. 七模組對應 endpoint 與測試案例。
3. 指標儀表板與實驗報告。
4. 部署手冊、操作手冊、風險處置流程。

## 12. 下一步（立即執行）
1. 先完成 Phase 0 的目錄與 config 重構。
2. 優先落地 `secure_tool_call` 與 `validate_output_structure`。
3. 補上最小稽核日誌，確保每次拒絕可追蹤。
