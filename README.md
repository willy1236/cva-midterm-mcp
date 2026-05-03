# cva-midterm-mcp

`cva-midterm-mcp` 是一個整合主機端（Host）、客戶端（Client）與模型上下文協議伺服器（Model Context Protocol Server, MCP Server）的系統。本專案透過 OpenAI 套件提供對話服務，並內建工具治理（Tool Governance）、輸出驗證（Output Validation）及資源熔斷機制（Resource Circuit Breaker），確保AI系統運行的安全性與穩定性。

## 核心功能 (Core Features)
* **上下文與策略管理 (Policy / Context Management)**：支援多種情境，並可依據上下文套用不同的系統提示詞（System Prompt）與工具使用權限。
* **工具治理 (Tool Governance)**：嚴格控管工具呼叫，檢測參數意圖，並記錄所有允許與拒絕的動作至稽核日誌（Audit Log）。
* **資源熔斷機制 (Resource Circuit Breaker)**：即時監控 Token 消耗量、模型呼叫次數、工具頻率與執行延遲（Latency），超限時將自動中斷並保護系統。
* **引用驗證 (Citation Verification)**：要求模型產出時附帶 `[citation:1]` 格式的來源標記，確保回答的準確性與可追溯性。

## 系統需求 (Prerequisites)
* Python 版本：`>=3.13`

## 安裝指南 (Installation)
1. 複製專案原始碼：
   ```bash
   git clone <repository_url>
   cd cva-midterm-mcp
   uv sync
   ```

## 快速啟動 (Quick Start)
執行以下指令啟動 Host HTTP API 與本機 MCP Server：
```Bash
uv run main.py
```
或
```Bash
python main.py
```

## 專案架構 (Project Structure)
詳細功能：[點我](/docs/CURRENT_IMPLEMENTED_FEATURES.md)

host/：處理伺服器 HTTP API、會話狀態（Session State）、策略載入（Policy Loading）與各種驗證器（Validators）。

client/：提供使用者進行互動式操作的 CLI 工具。

mcpServer/：包含 FastMCP 伺服器與註冊的工具。

docs/：存放專案實作文件與功能規劃。

tests/：包含工具守門機制（Tool Gatekeeper）、資源熔斷（Circuit Breaker）等自動化測試模組。

```mermaid
graph TD

    subgraph Client [客戶端層 Client Layer]
        CLI[client/cli.py <br> 互動式 CLI]
    end

    subgraph External [外部服務]
        direction TB
        subgraph MCPServer [MCP 伺服器層]
            MCPApp[mcpServer/app.py <br> FastMCP 服務]
        end

        subgraph AIServer [AI Server層]
            OpenAI["OpenAI (SDK相容) API <br> 大語言模型"]
        end
    end
    subgraph Host ["主機層 (Host Layer)"]
        direction TB
        Server{核心調度器 <br> Server}

        %% 平行子模組
        Server <-->|1. 狀態維持| Session[會話管理模組 <br> Session]
        Server <-->|2. 規則讀取| Contexts[上下文管理模組 <br> Contexts]
        Server <-->|3. 資源監控| Breaker[資源熔斷模組 <br> Circuit Breaker]
        Server <-->|4. 工具審查| Gatekeeper[工具守門模組 <br> Tool Gatekeeper]
        Server <-->|5. 格式確保| Validator[輸出驗證模組 <br> Output Validator]
        %% Module 6: 內容安全與動態政策
        Server <-->|12.5 內容分類| Classifier["內容分類模組 <br> classify_content()"]
        Classifier -->|分類結果| PolicyEnforcer["政策執行模組 <br> enforce_policy()"]
        PolicyEnforcer -->|允許| CitationVerifier["引用驗證模組 <br> verify_citations()"]
        CitationVerifier -->|驗證通過| Validator

        Session -.-> Logger
        Contexts -.-> Logger
        Breaker -.-> Logger
        Gatekeeper -.->|記錄攔截與允許| Logger
        Validator -.->|記錄驗證結果| Logger
        Classifier -.->|記錄分類| Logger
        PolicyEnforcer -.->|記錄政策動作| Logger
        CitationVerifier -.->|記錄引用核查| Logger
        
        Logger[(稽核紀錄模組 <br> Governance Logger)]
    end



    Client <-- "HTTP 請求 (Health/Session/Chat)" --> Server
    Server <--> External
```
## 單輪對話流程

標註淺藍色為新增之模組功能，其餘為常規AI Agent的對話流程

```mermaid
flowchart TD
    U[使用者    ]
    U --> H["Host / Server：收到 POST /chat"]
    H --> C("取得 context profile\n[模組1：ConfigLoader]")
    C --> B("資源與預算檢查\n[模組7 Resource/Circuit Breaker]")
    B --> O["呼叫 OpenAI（可能回傳 tool_calls）"]
    O --> G("檢查模型欲呼叫之工具\n[模組4 Tool Governance]")
    G --> M["MCP Server：執行工具 call_tool()"]
    M --> V("驗證工具輸出\n[模組2 Output Validation]")
    V --> CL("內容分類\n[模組6 Content Safety]")
    CL --> P("政策執行\n[模組6 Dynamic Policy]")
    P --> VA("驗證最終回覆\n[模組2 Output Validation]")
    VA --> R["回傳 assistant_response {answer, sources} 給使用者"]
    R --> L["GovernanceLogger：全程記錄審計事件"]

    %% 樣式定義
    classDef module fill:#e8f0ff,stroke:#333,stroke-width:1px;

    %% 將所有標註模組編號的節點套用相同樣式
    class C,B,G,V,CL,P,VA,L module;
```

模組編號對照：

- 模組1：Context / Policy profile（`host/policies/config_loader.py`）
- 模組2：Output Validation（`host/validators/output_validator.py`）
- 模組3：Citation Verification（`host/validators/citation_verifier.py`，在政策驗證或來源核查時使用）
- 模組4：Tool Governance（`host/validators/tool_gatekeeper.py`，模型發出工具呼叫時檢查）
- 模組6：Content Safety / Dynamic Policy（`host/validators/content_classifier.py` 與 `host/policies/policy_enforcer.py`，在最終回覆前分類與依照政策決定是否輸出）
- 模組7：Resource / Cost Circuit Breaker（`host/validators/resource_circuit_breaker.py`，整輪執行中持續檢查資源限制）