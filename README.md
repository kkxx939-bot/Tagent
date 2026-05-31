# Tagent

Tagent 是一个面向测试工作的本地 Agent 原型。它接收用户自然语言请求，识别测试任务意图，按技能选择执行计划，读取需求、用例、Bug、接口和 Source 文件上下文，最后输出测试用例、自动化代码草稿、检索摘要、排查建议或能力缺口说明。

当前项目重点覆盖这些任务：

- 根据需求生成测试用例
- 根据测试用例或功能生成自动化代码草稿
- 检索需求、历史用例、Bug、接口资料
- 失败排查入口和工具调用框架
- Source 文件理解和生成阻断
- 意图识别评测和趋势报告

## 整体架构

```text
用户输入
  |
  v
query_processing
  - 标准化 query
  - 处理别名，例如 case -> 测试用例、登陆 -> 登录
  - 抽取 target、framework、traceId、source_refs、force_source_generation
  |
  v
filework/queryfile
  - 识别 query 里引用的本地文件或 URL
  - 解析 doc/docx/pdf/xlsx/txt/json/log 等 Source
  - 生成 source_profile，用于判断文档是否适合当前任务
  |
  v
Intent
  - 识别主意图
  - 判断 is_ready、missing_context、next_action
  - 可走 LLM，也有规则兜底
  |
  v
skills
  - 根据 intent 选择技能定义
  - 技能描述任务类型、可用上下文来源和工具集合
  |
  v
planner
  - 生成执行计划
  - 对稳定任务使用模板计划
  - 对不稳定或复杂任务可走模型规划
  - 校验 ask_user、finish、load_context、generate_artifact 等动作是否合法
  |
  v
executor
  - 执行计划步骤
  - 加载上下文、生成产物、调用工具、保存结果、汇总输出
  |
  v
memory
  - SessionMemory 记录本次任务运行态
  - LongTermMemory 保存任务摘要、用户偏好、反馈、项目画像
  |
  v
AgentResult
  - 输出 intent_result、selected_skill、plan、execution_result、final_output、warnings
```

## 核心模块

```text
main.py
  本地运行入口。

agent/
  Agent 主编排层。负责串联 query 清洗、Source 理解、意图识别、技能选择、规划、执行和结果输出。

Intent/
  主意图识别和失败排查意图识别。包含 LLM 识别和规则兜底。

query_processing/
  用户 query 标准化和结构化抽取。

filework/
  原始资料解析。包含需求、用例、Bug、接口、Source 文件处理。

RAGwork/
  本地知识检索。当前以 BM25/关键词检索为主，预留 embedding 和 rerank 能力。

planner/
  执行计划生成、模板计划、模型计划和计划校验。

executor/
  计划执行器。负责 load_context、generate_artifact、call_tool、save_artifact、finish 等动作。

skills/
  测试任务技能定义，例如 case_generation、automation_writing、failure_triage。

memory/
  短期任务记忆和长期本地记忆。

tools/
  工具注册、工具配置、日志查询等工具适配框架。

openviking/
  OpenViking 可选接入。用于把本地需求、用例、Bug、接口资料导入上下文服务，并通过 ContextBackend 切换检索来源。

EvalTest/
  评测体系。当前已有 Eval_intent。

data/
  本地测试资产和处理后的知识数据。
```

## 一次任务怎么运作

以输入：

```text
根据登录需求生成 case，然后生成 Playwright 自动化脚本
```

运行过程大致是：

```text
1. normalize_query
   把 case 标准化为测试用例，抽取 登录、需求、playwright 等上下文。

2. process_query_sources
   如果 query 里包含文档路径，读取并理解 Source 文件。

3. recognize_main_intent
   识别主意图为 CASE_GENERATION，并把 AUTOMATION_WRITING 作为复合任务后续意图。

4. get_skill
   选择 case_generation 技能。

5. build_plan
   生成稳定模板计划：
   load_context -> generate_artifact(test_case) -> validate_artifact -> load_context(automation_project) -> generate_artifact(automation_code) -> save_artifact -> finish

6. Executor.run
   按步骤读取 RAG 上下文，生成测试用例，再生成自动化代码草稿。

7. MemoryManager.complete_task
   生成 session_summary，并按策略写入长期记忆。

8. 返回 AgentResult
   输出 final_output、artifacts、warnings、summary。
```

## 状态语义

Tagent 的结果状态主要有：

```text
completed
  任务完整完成。

partial_completed
  任务部分完成。例如生成了自动化代码草稿，但缺少自动化项目路径，无法直接落库。

waiting_for_user
  缺少必要上下文，需要用户补充。例如只说“写 Playwright 自动化脚本”，但没有说明目标功能。

capability_gap
  当前 Agent 没有能力或工具完成任务。例如要求重启服务，但没有重启服务工具。

failed
  执行过程中发生错误。
```

## Source 文件处理

Tagent 支持从 query 中识别本地文件引用，例如：

```text
根据我桌面的文档：song_new.pdf，生成case
根据 /path/to/需求文档.docx 生成测试用例
```

Source 处理会做三件事：

```text
1. 解析文件内容
2. 生成 source_profile
3. 判断这个 Source 是否适合当前任务
```

如果用户要求生成测试用例，但 Source 被识别为 unknown 或非需求/API/用例类文档，默认会进入保守阻断：

```text
waiting_for_user
```

如果用户明确要绕过阻断，可以使用：

```text
force_source_generation=true
```

## 运行

本机运行：

```bash
cd /Users/gulf/PycharmProjects/Tagent
/opt/anaconda3/envs/Tagent/bin/python main.py "根据登录需求生成测试用例"
```

默认 query 在 `main.py` 的 `DEFAULT_QUERY`。

安装依赖：

```bash
pip install -r requirements.txt
```

需要真实调用 LLM 时，建议通过环境变量配置：

```bash
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_API_KEY="你的 key"
export LLM_MODEL="deepseek-v4-flash"
```

## 评测

当前已有意图识别评测：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py
```

运行完整集：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --suite full_eval
```

默认关闭 LLM，主要评测规则兜底和 query 标准化链路。需要评真实模型链路：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --allow-llm
```

评测报告会写入：

```text
EvalTest/Eval_intent/report/
  latest.json
  history.jsonl
  trend.csv
  trend.svg
  runs/*.json
```

## Docker

基础镜像用于运行 Tagent 主流程和评测：

```bash
docker build -t tagent:latest -f Dockerfile .
docker run --rm -it tagent:latest
```

Playwright 镜像用于执行 Web UI/E2E 自动化脚本：

```bash
docker build -t tagent:playwright -f Dockerfile.playwright .
docker run --rm -it tagent:playwright npx playwright --version
```

更多命令见 `docker.md`。

## OpenViking

Tagent 当前保留本地 RAG，同时也接了一个可选的 OpenViking backend。它的作用是把需求、用例、Bug、接口资料导入独立上下文服务，再通过统一的 `ContextBackend` 返回给 executor。

本地常用命令：

```bash
python main.py "检索登录相关需求资料"
python main.py openviking "检索登录相关需求资料"
python -m openviking.ingest --execute --wait
python -m observability.openviking_observation_run
python -m observability.openviking_compare_report
```

切换到 OpenViking backend 时主要依赖这些环境变量：

```bash
export CONTEXT_BACKEND=openviking
export OPENVIKING_URL=http://localhost:1933
export OPENVIKING_TARGET_URI=viking://resources/tagent
```

完整实验记录、Docker 本地服务、数据导入、接入前后数据结构和观测结果见 `OpenViKing.md`。

## 目前边界

当前 Tagent 仍然是本地原型，工业化能力还在补齐：

- 工具执行层还没有完整接真实日志平台、数据库、CI、自动化平台。
- RAG 当前以本地处理文件和关键词检索为主，向量检索和 rerank 是预留能力。
- Memory 当前是本地 json/jsonl，适合 MVP，但还缺少生命周期治理和语义检索。
- 自动化代码生成目前是草稿产物，还没有完整落库和执行闭环。
- 评测目前已有 Eval_intent，后续还需要 Eval_source、Eval_rag、Eval_planner、Eval_case_generation、Eval_e2e。

## 后续方向

```text
1. 标准 AgentRequest / AgentResponse
2. CLI 和 SDK 入口
3. Source / RAG / Memory 的 Context Manager
4. token 和上下文使用观测
5. 接口自动化和 UI 自动化执行工具
6. Eval_source、Eval_rag、Eval_planner、Eval_case_generation、Eval_e2e
7. OpenViking 或其他 Context Backend 的可选接入
```
