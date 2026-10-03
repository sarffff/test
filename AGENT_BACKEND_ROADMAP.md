# Agent 后端开发路线图（2026 趋势版，以后端为主）

> 适用：从 0 到 1 做通用 Agent 后端，不基于现有 RAG 进度。
> 趋势依据：MCP（Agent→Tool 标准，月下载 164M+）+ A2A v1.2（Agent↔Agent 生产可用）、Agentic RAG（ReAct / Self-RAG / Corrective RAG）、长记忆突破、多 Agent 协作、控制平面安全（身份/审计/零信任）。
> 核心判断：ACL'26 `Is Agentic RAG worth it?` —— 简单问用固定管线更便宜，只有模糊/多跳问才值得开 Agent 循环。所以顺序是 **先标准化、再单 Agent、再记忆与纠错、最后多 Agent**。

## 0. 设计原则（贯穿所有阶段）

1. **协议先行**：Tool 用 MCP 格式，Agent 间用 A2A 格式，自己造的私有 `function_call` 只做适配层。
2. **检索只是 Tool 之一**：不要先做 RAG 再套 Agent，要先有 Agent Loop，再把检索挂上去。
3. **每阶段可评估**：先有 Eval Harness 再做优化，否则 Agentic 的迭代就是玄学。
4. **成本可观测**：token / 延迟 / 工具调用次数从 Day 1 打点，Agentic 成本是 Naive RAG 的 3-10x。
5. **同步转异步**：LLM 推理 + 检索 + 工具都是慢 IO，全链路 `async + SSE`，不要同步阻塞。

## 1. 技术选型（建议冻结，不随阶段变）

```text
API:        FastAPI + SSE (stream) + Pydantic v2
Agent编排:  自研 ReAct Loop（<300行）优先，跑通后再考虑 LangGraph / CrewAI
            理由：自研可控、可打点；框架只解决编排，不解决 Eval/记忆/安全。
LLM网关:    OpenAI-compatible Client，LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 可换源
            对话模型与 Embedding 模型解耦配置
DB:         PostgreSQL + pgvector（文档/记忆/注册表统一）+ Redis（会话/队列/缓存/限流）
            初期可用 SQLite + Chroma 过渡，但接口要按 Postgres 抽象。
任务队列:   Celery / RQ / FastAPI BackgroundTasks（文档索引、批量评估异步化）
可观测:     Langfuse / OpenTelemetry + 结构化日志（trace_id 贯穿 query→plan→tool→llm）
评估:       自建 golden set + Hit/MRR（检索层）+ RAGAS 四件套（端到端）
安全:       API Key / JWT + 按 doc_id/tenant_id 过滤 + 审计日志
```

终态目录（后端视角）：

```text
app/
  main.py              # FastAPI 入口：/chat /tools /agents /eval /health
  config.py            # env 配置中心
  llm/gateway.py       # 统一 LLM/Embedding 调用，重试/降级/计费
  tools/registry.py    # 工具注册表（MCP 兼容）
  tools/*.py           # web_search / rag_search / sql / http / code_exec
  agent/loop.py        # ReAct 主循环：plan→act→observe→reflect
  agent/planner.py     # 查询分解、路由（是否检索/是否委派）
  agent/verifier.py    # Corrective/Self-RAG 打分与纠错
  memory/short.py      # 会话历史（Redis，窗口+摘要）
  memory/long.py       # 长期记忆（pgvector，用户画像/偏好/事实）
  knowledge/ingest.py  # 文档接入→解析→清洗→分块→向量化
  knowledge/search.py  # Dense + Sparse + RRF + Rerank
  eval/harness.py      # 合成测试集 + 指标 + 矩阵对比
  observability/       # trace / metrics / cost
  mcp/server.py        # 对外暴露 MCP Server
  a2a/server.py        # 对外暴露 A2A Agent Card + Task 接口
```

---

## 2. P0 — LLM 网关 + API 骨架（1-2 天）

**为什么最先做**：没有统一网关，后面所有 Agent/Eval 都无法切模型、算成本。

- 做什么：
  - `POST /api/chat`（非流式先跑通，预留 `SSE /api/chat/stream`）。
  - `GET /api/health`。
  - LLM Client 封装：timeout / 重试（指数退避）/ temperature 分场景（问答 0.3，对话 0.7，规划 0）。
  - 配置中心：model / base_url / key / embedding 模型 / top_k / 阈值全走 env。
  - trace_id + 耗时 + token 用量日志。
- 验收：换 `LLM_MODEL` 不改代码可跑；单次问答延迟/用量可见。
- 坑：不要在业务代码里直调 `OpenAI()`，必须收敛到 `llm/gateway.py`。

## 3. P1 — Tool 协议层（MCP 兼容，3-5 天）

**为什么第二**：2026 共识是 `MCP=垂直层（Agent→Tool），A2A=水平层（Agent↔Agent）`。先有标准 Tool，Agent 才可移植。

- 做什么：
  - `Tool = {name, description, json_schema, handler}` 注册表。
  - 先做 3 个样板 Tool：`get_time`、`http_fetch`、`echo`，验证协议。
  - 实现 `MCP Server` 暴露（`/mcp` SSE/stdio 二选一），让 Claude Desktop / Cursor 能调到你的 Tool。
  - Tool 执行沙箱：超时、参数校验、错误结构化返回（给 LLM 看的，不是堆栈）。
- 验收：第三方 MCP Client 能 list/call 你的 Tool；非法参数不崩服务。
- 坑：Tool 描述写不好，LLM 永远调不对。描述要写触发条件 + 示例 + 反例。

## 4. P2 — 单 Agent ReAct 主循环（核心，1-2 周）

**为什么此时做**：有网关 + 有 Tool，才能做 `Think→Act→Observe` 循环。这是 Agent 和 Chatbot 的分水岭。

- 做什么：
  - `agent/loop.py`：
    ```text
    while steps < max_steps:
      plan = llm(goal, history, tools)
      if plan == final_answer: break
      obs = tools.call(plan.tool, plan.args)
      history.append(obs)
    ```
  - `max_steps=6`、`超时控制`、`中间产物截断`（防上下文爆炸）。
  - 系统提示词分三段：角色 / 工具使用规范 / 停止条件。
  - SSE 流式输出 `plan / tool_call / observation / answer` 事件，前端可渲染思考链。
- 验收：`“查北京天气并换算成华氏度”` 能自主调 2 个 Tool 完成；死循环可熔断。
- 坑：不要一上来做规划器多模型，单模型 + 清晰 prompt 足够跑通 80%。

## 5. P3 — 知识库作为 Tool（Agentic RAG，1-2 周）

**为什么挂在 Agent 下**：检索只是 `rag_search` Tool，不是主链路。Agent 自主决定是否检索、检索几次。

- 做什么：
  - `knowledge/ingest.py`：txt/md/html/pdf → 清洗 → 500字结构分块 + overlap → 向量化入库。
  - `knowledge/search.py`：Dense（pgvector cosine）+ BM25 + RRF 融合，`MIN_SCORE` 过滤。
  - 暴露为 Tool：`rag_search(query, top_k)`，返回 `[{doc_id, chunk, score, source}]`。
  - 路由策略：简单问直答，`我们的/文档/配置` 类问强制走 `rag_search`。
- 验收：Hit Rate@4 / MRR 有基线数字；空检索明确拒答不幻觉。
- 坑：块太大稀释相似度、太小丢上下文；先固定 500/50 跑 Eval 再调。

## 6. P4 — 记忆系统（短期 + 长期，1 周）

**为什么现在做**：Loop 和检索跑通后，多轮指代（`它/上面那个`）立刻成为瓶颈。2026 记忆是拉开体验的关键。

- 做什么：
  - 短期：Redis 会话 `session_id → 最近 N 轮`，超限做摘要压缩。
  - 长期：pgvector 存 `用户事实/偏好`（如 `常用模型=gpt-4o`），检索时注入 system prompt。
  - 查询改写：用历史 + 当前问生成检索友好查询（复用 P2 的 LLM 调用）。
  - 遗忘/TTL：会话 7 天，长期记忆可删除、可审计。
- 验收：`“它端口是多少？”` 第二轮能正确消解；换 session 不串记忆。
- 坑：全量历史塞 prompt 必爆 token，必须窗口 + 摘要 + 按需检索。

## 7. P5 — 纠错与规划升级（Corrective / Self-RAG，1-2 周）

**为什么靠后做**：需要 Eval Harness 才能证明有效，否则就是加延迟。

- 做什么：
  - `agent/verifier.py`：对检索结果打 `relevant / ambiguous / irrelevant`。
  - Corrective 动作：`relevant→生成`，`ambiguous→改写再检`，`irrelevant→扩检/web_search fallback`。
  - Self-check：生成后让 LLM 自查是否忠于引用，引用格式 `[1][2]` 对应 chunk。
  - 可选：HyDE（先生成假设答案再检索）、查询分解（复杂问拆 2-3 子查询）。
  - Rerank：`bge-reranker / Cohere` 对 top-20 精排取 top-4，精度提升最大但最贵，放开关里。
- 验收：同一 golden set 上 Faithfulness 提升，延迟增幅可接受；开关可回退到 P3。
- 坑：每个纠错都是一次 LLM 调用，`max_retries=1` 封顶，否则成本失控。

## 8. P6 — 评估与可观测（与 P5 并行，必须做）

- 做什么：
  - 检索层：LLM 合成测试集（块→反向生成问题）+ Hit Rate / MRR / 参数矩阵（top_k × min_score）。
  - 端到端：RAGAS Faithfulness / Answer Relevancy / Context Precision/Recall，LLM-as-judge。
  - 线上：Langfuse trace（query→plan→tool→rerank→answer 全链），按 trace 复盘坏 case。
  - 成本看板：单问 token、工具次数、缓存命中率。
- 验收：每次改 prompt/阈值/分块，先跑 `eval` 再合入；有回归报告文件。
- 坑：没有 golden set 的优化一律视为玄学。

## 9. P7 — 多 Agent 与 A2A（最后做，2-3 周）

**为什么最后**：单 Agent 不稳，多 Agent 是指数复杂度。A2A v1.2 已生产可用，但只解决互联，不解决单体质量。

- 做什么：
  - 先做两种固定编排即可：
    - `路由委派`：主 Agent 按意图委派给 `检索Agent / 代码Agent / 搜索Agent`。
    - `流水线`：Reporter→Researcher→Editor→Publisher（新闻/研报类）。
  - 暴露 `A2A Agent Card`：`{name, skills, endpoint, auth}` + Task 生命周期（pending/running/done）。
  - 人机回环：高风险 Tool（删除/发邮件/支付）必须 `elicitation` 等人确认。
- 验收：跨框架（LangGraph 调你的 A2A Agent）可跑通；子 Agent 失败可降级为单 Agent。
- 坑：不要做去中心化自治群聊，先做中心化 orchestrator，可调试性高一个量级。

## 10. P8 — 安全、权限、多租户、上线（落地前必做）

- 做什么：
  - 身份：JWT/API Key→`tenant_id/user_id`，检索强制 `where tenant_id=`。
  - 审计：谁、何时、调了什么 Tool、看到了什么 doc_id，全日志。
  - 限流/配额：按租户限 QPS/token/文件大小；大文件异步索引（上传即返回 task_id，轮询进度）。
  - Prompt 注入防线：系统指令与用户内容/检索内容隔离，工具参数白名单。
  - 部署：Docker + 迁移脚本（pgvector 索引）+ 健康检查 + 优雅停机。
- 验收：A 租户搜不到 B 文档；注入 `忽略之前指令` 不执行高危 Tool。
- 坑：权限过滤必须在检索层做（SQL where），不能靠 LLM 自觉过滤。

---

## 里程碑总览

| 阶段 | 产出 | 是否可跳过 |
|---|---|---|
| P0 网关+API | 可换模型的对话后端 | 否 |
| P1 MCP Tool | 标准工具层 | 否 |
| P2 ReAct Loop | 单 Agent 可自主调工具 | 否 |
| P3 RAG Tool | 知识库问答 | 可延后（无私有知识可跳） |
| P4 记忆 | 多轮可用 | 否（多轮场景） |
| P5 纠错/Rerank | 幻觉率下降 | 否 |
| P6 评估/观测 | 优化有据可依 | 否 |
| P7 A2A多Agent | 复杂任务委派 | 是（单Agent够用就别做） |
| P8 安全多租户 | 可上线 | 否（对外就必须） |

**一句话顺序**：`网关 → MCP工具 → 单Agent循环 → RAG变工具 → 记忆 → 纠错+评估 → 多Agent(A2A) → 安全上线`。
