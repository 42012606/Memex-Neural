# 🤖 AI Context Archiving SOP (通用存档标准)

> **Trigger**: 当用户发送“存档”、“Save Context”或“总结本窗口”时触发。
> **Goal**: 将当前会话的**短期记忆**固化为**长期文档**，使下一个 AI Session 能准确继承进度。
> **Core Principle**: 文档是 AI 的长期记忆。AI_MAP 必须足够详细，以便新窗口的 AI 能直接命中代码文件。

## 🛑 Phase 1: 智能回顾 (Session Review)
在修改文档前，请先执行以下思维链：
1.  **回顾变更**: 本次会话我们修改了哪些核心文件？解决了什么 Bug？新增了什么功能？
2.  **定位进度**: 对照旧的 `NEXT_TASK.md`，哪些 P0 任务已完成？是否产生了新的 P0？
3.  **架构检查**: 是否引入了新的依赖、新的表结构或新的核心类？（如有，需同步至 AI_MAP）。

---

## 🏗️ Phase 2: 更新记忆三件套 (Update Trinity)

请**读取并更新**以下三个文件（如不存在则创建）。请保持模板结构，但内容要根据项目实际情况动态填充。

### 📄 1. 更新 `README.md` (现状仪表盘)
* **核心目标**: 让 AI 和人一眼看到项目的**生命体征**。
* **通用模板结构**:
    ```markdown
    # [Project Name]

    > **📊 Status Dashboard**
    > * **Version**: [e.g., v0.5.0]
    > * **Last Update**: [YYYY-MM-DD]
    > * **Health**: [e.g., Core Functionality Stable / UI Needs Fixes]

    ## 1. 🎯 Project Overview (项目全景)
    * **核心目标**: [一句话描述项目是做什么的]
    * **当前能力 (What Works)**:
        * [✅] [已跑通的功能 A]
        * [✅] [已跑通的功能 B]
        * [🚧] [开发中/不稳定的功能 C]

    ## 2. 🛠️ Quick Start & Env (环境摘要)
    * **Tech Stack**: [列出核心技术栈]
    * **Key Config**: [列出关键环境变量名，不含敏感值]
    ```

### 🗺️ 2. 更新 `AI_MAP.md` (核心代码地图)
* **核心目标**: **精准导航**。新窗口的 AI 必须能通过此表快速知道“修改 X 功能要去 Y 文件”。
* **执行要求**: 
    * 扫描项目中的核心代码文件（排除 venv, node_modules 等）。
    * **必须** 包含“File Description”列，用一句话总结该文件负责什么业务逻辑。
* **通用模板结构**:
    ```markdown
    # 🧠 AI Architecture Map & Code Index

    > **Instruction**: 在修改代码前，必须查阅本表以定位正确的文件路径。

    ## 1. 📍 Codebase File Index (核心文件职责)
    *(动态更新：列出当前项目中最重要的逻辑文件)*

    | File Path (路径) | Primary Responsibility (核心职责) | Key Classes/Functions (关键组件) |
    | :--- | :--- | :--- |
    | `src/main.py` | FastAPI 入口，挂载路由与中间件 | `app`, `lifespan` |
    | `src/services/processor.py` | **核心**: 处理文件归档流水线(OCR/移动/入库) | `process_file`, `_generate_path` |
    | `src/api/chat.py` | 处理用户对话请求，调用 RAG 链路 | `chat_endpoint` |
    | `[Add more files...]` | [Description...] | [...] |

    ## 2. 🌊 Critical Data Flow (核心链路)
    *(描述数据如何在上述文件间流转)*
    * **Upload Flow**: `api/upload.py` (Receive) -> `services/processor.py` (Async Task) -> `DB (archives)` -> `Vector Service`
    * **Chat Flow**: `api/chat.py` (Request) -> `agents/router_agent.py` (Intent) -> `services/retrieval` (Search) -> `LLM`

    ## 3. 🛡️ Development Rules (开发红线)
    *(记录项目中绝对不能违反的规则)*
    1. [例如: 物理路径必须包含 user_id]
    2. [例如: 禁止在前端直接拼接 SQL]
    ```

### 📅 3. 更新 `NEXT_TASK.md` (施工日志与交接)
* **核心目标**: **无缝交接**。总结刚才做了什么，规划接下来做什么。
* **通用模板结构**:
    ```markdown
    # 📅 Task & Handoff Log

    ## 1. 📝 Session Summary (本次工作总结)
    *(本次会话完成了什么？)*
    * **Done**: [完成了任务 A]
    * **Fixed**: [修复了 Bug B]
    * **Changes**: [修改了文件 X, Y, Z]

    ## 2. 🚀 Next Priorities (接力任务)
    *(接手的 AI 应该立刻做什么？)*
    * **P0 (Immediate)**: [具体的下一步动作]
    * **P1 (Queue)**: [后续计划]

    ## 3. 🧠 Context Handoff (给继任者的留言)
    *(用第一人称写一段话，交代隐性知识)*
    > "你好，我是上一轮的 AI。我刚刚把 [功能] 跑通了，但是 [某个边缘情况] 可能还没测。建议你下一轮先从 [测试/完善] 开始..."
    ```

---

## ✅ Phase 3: 存档确认 (Verify)
更新完上述文件后，请在聊天窗口输出：
1.  **"✅ 存档已完成"**
2.  **变更摘要**: 简述刚才更新了哪些文档的关键点。
3.  **下一步指令**: 生成一条建议用户发送给新窗口 AI 的 prompt。