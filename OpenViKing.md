# Tagent 接入 OpenViking 的实验记录

这份记录不是最终方案设计文档，更像一次接入实验的流水账。目的是把这次为什么接、怎么接、跑出来的数据是什么、哪些地方确实变好了、哪些地方还没变好，都留在一个地方。后面如果继续往生产方向做，可以在这份记录上继续追加。

这次先不讨论 OpenViking 在真实业务生产环境里的最佳实践。生产环境会涉及业务数据结构、权限隔离、项目空间、成本预算、部署规模、模型服务、数据安全和运维策略，这些都需要结合具体公司和具体业务看。这里记录的是 Tagent 当前本地数据集上的轻量实验。

## 背景

Tagent 目前已经有本地 RAG、Memory、文件解析、意图识别、计划执行和观测能力。问题是数据越来越多以后，本地上下文拼装会遇到几个明显问题：

1. query 比较宽泛时，容易召回多个领域的资料。
2. 上下文会变长，进入 prompt 的 token 成本会变大。
3. Memory 和 RAG 的命中结果虽然能拿到，但不容易从 URI、项目、模块、文件这些维度稳定追踪。
4. 本地逻辑和未来可能的统一上下文服务之间缺少一层可替换的 backend。

所以这次接 OpenViking，不是为了马上替换所有本地逻辑，而是先验证它能不能作为 Tagent 的上下文 backend，至少回答几个问题：

- 能不能把 Tagent 本地资料导进去。
- 能不能通过统一 URI 找回上下文。
- 接入后 token、延迟、噪声、可追踪性有没有变化。
- 如果后面真的接入生产服务，Tagent 需要改哪些结构。

## 当前实验结论

从这轮本地实验看，结论比较直接：

- OpenViking 已经能接入 Tagent 的上下文加载链路。
- 38 个本地资料文件已经成功导入本地 OpenViking 服务。
- 接入后，整体上下文 token 和加载耗时明显下降。
- 宽泛 query 的噪声没有降下来，甚至在当前启发式统计下变高。
- 更具体的 query，例如带上“XZ银行 手机银行 注册登录模块”，噪声可以降到 0。
- 当前仍会召回一些 `.overview.md` 节点，说明还需要继续处理召回粒度。
- `cross_project_context_rate` 当前还不可靠，因为现在的判断规则会把 query 里的“银行”和 OpenViking URI 中统一的 `tagent` 项目名做错配。

一句话总结：这次接入证明 OpenViking 作为上下文 backend 是能跑通的，也确实能减少 token 和延迟；但要让召回质量稳定变好，还需要继续做 URI 设计、metadata、过滤和 rerank。

## 本地启动方式

OpenViking 官方支持两种启动方式：

- 作为 Python 包安装，用作本地库。
- 作为独立服务启动，Docker 是比较推荐的方式。

这次 Tagent 走的是 Docker 本地服务模式。主要原因是 Tagent 自己是一个 Agent 应用，不希望把 OpenViking 作为进程内依赖绑死。独立服务更接近以后工业化部署的方式，也方便把上下文服务和 Agent 运行进程拆开。

本地服务配置放在：

```text
~/.openviking/ov.conf
```

本次实验使用了一个本地 root key：

```json
{
  "server": {
    "root_api_key": "tagent-local-dev-key"
  }
}
```

注意：这个 key 只是本地实验用。生产环境不能把 key 写进仓库，也不能直接复用这个值。

Docker 镜像部分，这次没有直接只用官方镜像，而是加了一个本地 Dockerfile：

```text
openviking/Dockerfile.local
```

原因是第一次启动时，本地 embedding 相关依赖缺失，服务侧需要 `llama-cpp-python` 这类本地 embedding 依赖。最终本地镜像是基于官方镜像再安装：

```text
openviking[local-embed]
```

当前实验服务信息：

```text
container: tagent-openviking
image:     tagent-openviking-local:latest
port:      1933
ui:        http://localhost:1933/studio
status:    healthy
```

Docker 服务启动后，Tagent 侧通过环境变量连接：

```bash
OPENVIKING_URL=http://localhost:1933
OPENVIKING_API_KEY=tagent-local-dev-key
OPENVIKING_ACCOUNT=default
OPENVIKING_USER=tagent
OPENVIKING_TARGET_URI=viking://resources/tagent
CONTEXT_BACKEND=openviking
```

其中 `CONTEXT_BACKEND=openviking` 是 Tagent 切换上下文 backend 的开关。

## 数据导入

这次导入的数据来自 Tagent 本地 `data` 目录：

```text
data/requirements
data/test_cases
data/bugs
data/api_docs
```

导入脚本放在：

```text
openviking/ingest.py
```

导入逻辑分两步：

1. 先调用 OpenViking 的临时文件上传接口。
2. 再调用资源创建接口，把文件挂到指定 URI。

本次统一挂到：

```text
viking://resources/tagent
```

不同类型的数据会继续拆到下一级：

```text
viking://resources/tagent/requirement/xxx.docx
viking://resources/tagent/case/xxx.xlsx
viking://resources/tagent/bug/xxx.xlsx
viking://resources/tagent/api/xxx.md
```

这次导入结果保存在：

```text
result/openviking_ingest_result.json
```

导入结果：

```text
total:     38
succeeded: 38
failed:    0
```

也就是说，当前实验不是只接了一个 mock，而是真的把 Tagent 本地资料写进了 OpenViking 服务。

后面你可以把 Docker 的 CPU、内存、写入过程截图补在这里。建议截图至少包含：

- Docker 容器健康状态。
- 导入时 CPU 波动。
- 导入完成后的 `total/succeeded/failed`。
- OpenViking Studio 中资源树或资源列表。

## 接入前的数据传递

接 OpenViking 之前，Tagent 的上下文大致是这样走的：

```text
user_query
  -> query_processing 标准化
  -> intent 识别
  -> planner 生成步骤
  -> executor 执行 load_context
  -> context.build_case_context(query)
  -> 本地 requirement/case/bug/api 检索
  -> 拼成 source_summary 和上下文片段
  -> generate_artifact / summarize_result
  -> final_output
```

这个链路的问题不是不能用，而是上下文加载逻辑和本地数据结构耦合比较重。比如 case 生成、上下文检索、失败排查都会去拿本地资料，但“怎么拿资料”这个动作没有抽象出来。

所以之前的数据传递更像：

```text
业务步骤直接调用本地 RAG 函数
```

本地 RAG 返回以后，executor 再把这些内容塞进执行结果里。

优点是简单，缺点是后面换检索引擎、换记忆系统、换远端上下文服务时，改动会扩散。

## 改造后的数据传递

这次加了一个统一入口：

```text
ContextBackend.py
```

里面定义了几个核心结构：

```text
ContextRequest
ContextResult
ContextBackend
LocalRagBackend
OpenVikingBackend
```

改造后的链路变成：

```text
user_query
  -> query_processing 标准化
  -> intent 识别
  -> planner 生成步骤
  -> executor 执行 load_context
  -> ContextBackend.load(ContextRequest)
      -> local backend
      或 openviking backend
  -> ContextResult
  -> executor 继续执行后续步骤
  -> final_output + observability
```

也就是说，executor 不需要关心上下文到底来自本地 RAG，还是来自 OpenViking。它只关心 `ContextResult`。

本地 backend：

```text
ContextBackend.LocalRagBackend
  -> context.build_case_context(query)
```

OpenViking backend：

```text
openviking.backend.OpenVikingBackend
  -> openviking.client.OpenVikingClient.search()
  -> OpenViking /api/v1/search/find
  -> openviking.mapper.response_to_context()
```

这个改造的价值在于：后面如果要加别的上下文系统，不需要推翻 executor，只需要继续实现新的 backend。

## 接入前后的数据结构

上一节讲的是链路，这里单独把数据结构写清楚。因为这次接 OpenViking，真正重要的不是多调了一个服务，而是把“上下文从哪里来”和“上下文在 Tagent 里怎么用”拆开了。

### 接入前：本地 RAG 直接返回业务上下文

接 OpenViking 之前，executor 在 `load_context` 阶段拿到的结构更偏本地业务上下文。它大概长这样：

```json
{
  "source_summary": {
    "requirement": {
      "count": 4,
      "chunk_ids": [
        "requirement_006138",
        "requirement_003633"
      ]
    },
    "case": {
      "count": 4,
      "chunk_ids": [
        "case_009456",
        "case_009208"
      ]
    },
    "bug": {
      "count": 2,
      "chunk_ids": [
        "bug_000184",
        "bug_000173"
      ]
    },
    "api": {
      "count": 2,
      "chunk_ids": [
        "api_000001",
        "api_000007"
      ]
    }
  }
}
```

有些场景里还会带上更具体的片段、文件来源、项目字段、feature 字段，最后进入观测时会被统计成：

```json
{
  "traceability": {
    "context_count": 12,
    "traceable_context_count": 12,
    "project_counts": {
      "KIMS": 2,
      "信贷业务": 2,
      "车机": 3
    },
    "source_file_counts": {
      "data/requirements/xxx.docx": 1,
      "data/test_cases/xxx.xlsx": 3
    }
  }
}
```

这个结构的特点是：

- 它直接服务 Tagent 的业务动作，比如生成 case、检索上下文、失败排查。
- `requirement/case/bug/api` 是 Tagent 自己的数据分类。
- `chunk_id` 也是本地生成的 ID。
- 数据来源能追，但不是统一 URI。
- 如果换一个检索系统，executor 和 context loader 很容易被影响。

所以接入前的结构可以理解为：

```text
本地检索结果
  -> 按 Tagent 业务分类组织
  -> 直接给 executor 使用
```

### 接入后：OpenViking 返回资源节点

接入 OpenViking 后，原始返回不再是 Tagent 自己的 `requirement/case/bug/api` 结构，而是更像“资源节点”。每个节点背后有 URI、文本、来源和分数。

简化后大概是这样：

```json
{
  "status": "ok",
  "result": {
    "total": 12,
    "items": [
      {
        "uri": "viking://resources/tagent/requirement/某需求文档.docx/xxx",
        "text": "这里是召回的文档片段",
        "score": 0.82,
        "metadata": {
          "source_file": "某需求文档.docx",
          "source_type": "requirement"
        }
      }
    ]
  }
}
```

实际字段会以 OpenViking 服务返回为准，但核心变化是：

- 上下文有了统一 URI。
- 一个片段可以追到 OpenViking 资源路径。
- 以后可以按 URI 做项目、模块、版本、文件级隔离。
- 检索系统返回的是“资源节点”，不直接等于 Tagent 的业务上下文。

也就是说，OpenViking 返回的数据结构更通用，但 Tagent 不能直接无脑消费。中间需要一层映射。

### 中间层：统一成 ContextResult

为了解决这个问题，这次加了 `ContextBackend.py`，用 `ContextRequest` 和 `ContextResult` 作为 Tagent 内部的统一结构。

请求结构：

```json
{
  "context_type": "case_generation",
  "query": "根据登录需求生成测试用例",
  "inputs": {},
  "variables": {},
  "filters": {}
}
```

返回结构：

```json
{
  "success": true,
  "backend": "openviking",
  "context": {
    "source_summary": {
      "requirement": {
        "count": 4,
        "chunk_ids": []
      },
      "case": {
        "count": 4,
        "chunk_ids": []
      },
      "bug": {
        "count": 2,
        "chunk_ids": []
      },
      "api": {
        "count": 2,
        "chunk_ids": []
      }
    },
    "context_items": [
      {
        "uri": "viking://resources/tagent/requirement/某需求文档.docx/xxx",
        "text": "召回片段",
        "source_type": "requirement",
        "source_file": "某需求文档.docx",
        "score": 0.82
      }
    ]
  },
  "warnings": [],
  "error": null,
  "metadata": {
    "context_type": "case_generation",
    "query": "根据登录需求生成测试用例",
    "target_uri": "viking://resources/tagent",
    "search_mode": "find",
    "node_limit": 12,
    "openviking_total": 12
  }
}
```

这里有个关键点：`ContextResult` 是 Tagent 自己的稳定结构。OpenViking 可以换成本地 RAG，后面也可以换成别的上下文服务，但 executor 尽量只看 `ContextResult`。

### 结构变化总结

接入前：

```text
executor
  -> context.build_case_context(query)
  -> 本地 source_summary / chunk_ids
  -> executor 直接使用
```

接入后：

```text
executor
  -> ContextBackend.load(ContextRequest)
  -> OpenVikingBackend
  -> OpenViking resource nodes
  -> response_to_context()
  -> ContextResult
  -> executor 使用统一 context
```

所以这次改的数据结构主要是三层：

| 层级 | 接入前 | 接入后 |
| --- | --- | --- |
| 检索输入 | query 字符串 | `ContextRequest` |
| 检索结果 | 本地 `source_summary` 和 chunk | OpenViking resource nodes |
| Tagent 内部消费 | 直接消费本地结构 | 消费统一 `ContextResult` |
| 可追踪字段 | 本地文件路径、chunk_id | URI、source_file、source_type、metadata |
| backend 切换 | 不明显 | `CONTEXT_BACKEND=local/openviking` |

这里后面还要继续补一件事：导入 OpenViking 时，把 `project/domain/module/version/source_type` 这些 metadata 写进去。现在结构已经能承接这些字段，但数据还没有完全补齐。

## OpenViking 侧请求结构

Tagent 当前查询 OpenViking 时，主要传这些字段：

```json
{
  "query": "用户 query",
  "target_uri": "viking://resources/tagent",
  "node_limit": 12,
  "include_provenance": false,
  "telemetry": false
}
```

如果后面需要更细的过滤，还可以继续打开：

```text
OPENVIKING_SCORE_THRESHOLD
OPENVIKING_LEVEL
OPENVIKING_USE_METADATA_FILTER
OPENVIKING_INCLUDE_PROVENANCE
```

目前还没有把 metadata filter 用重。也就是说，现在主要是靠 query 和 target_uri 做召回，没有强制按 `source_type=需求文档`、`domain=银行`、`module=登录注册` 去约束。这也是宽泛 query 噪声没有降下来的主要原因之一。

## 观测体系

为了看 OpenViking 接入前后到底有没有变化，这次没有只看主观感觉，而是加了几类观测：

```text
observability/token_observation.py
observability/context_observation.py
observability/memory_observation.py
observability/llm_observation.py
observability/agent_observation.py
observability/openviking_observation_run.py
observability/openviking_compare_report.py
```

主要指标：

```text
estimated_total_tokens
estimated_context_tokens
context_count
noise_context_count
noise_context_rate
cross_project_context_count
cross_project_context_rate
traceable_context_count
traceable_context_rate
memory_hit_count
load_context_total_ms
```

这些数据会写到：

```text
result/openviking_observation_baseline_local.json
result/openviking_observation_after_openviking.json
result/openviking_query_observation_records.json
```

为了后面方便看单个 query 的结果，又整理了一层：

```text
result/query_compare
```

现在是一个 query 一个目录：

```text
result/query_compare/context_login_requirements/compare.json
result/query_compare/context_login_requirements/compare.csv
```

`compare.json` 是结构化记录，`compare.csv` 是表格对比。

## 接入前后整体数据

当前 baseline 是本地 RAG/Memory：

```text
result/openviking_observation_baseline_local.json
```

接入后是 OpenViking backend：

```text
result/openviking_observation_after_openviking.json
```

整体数据如下：

| 指标 | 接入前 local | 接入后 OpenViking | 变化 |
| --- | ---: | ---: | ---: |
| estimated_total_tokens | 32948 | 25667 | -7281 |
| estimated_context_tokens | 19262 | 6332 | -12930 |
| context_count | 48 | 48 | 0 |
| noise_context_rate | 0.5556 | 0.8889 | +0.3333 |
| traceable_context_rate | 1.0 | 1.0 | 0 |
| memory_hit_count | 20 | 20 | 0 |
| load_context_total_ms | 10849.13 | 279.69 | -10569.44 |

这组数据说明：

- token 是明显下降的，尤其是上下文 token。
- 上下文加载耗时下降明显。
- 上下文条数没有变，因为当前 node_limit 还是固定拿 12 条左右。
- 可追踪率仍然是 1.0，说明 URI 和文件来源还能追。
- 噪声比例没有改善，说明“能召回”和“召回得准”不是一回事。

所以这里不能简单说 OpenViking 已经全面变好了。更准确地说：

```text
OpenViking 接入后，传输成本和加载耗时变好了；
召回质量还没完全变好，需要继续调 URI、metadata 和过滤策略。
```

## 为什么一开始噪声没有降下来

一开始用的是比较宽泛的 query：

```text
检索登录相关需求资料
```

这个 query 的问题是“登录”太泛。Tagent 当前本地数据里有银行、车机、租房、信贷、社区 SaaS 等不同领域。只要文档里出现登录、用户、账号、资料、接口等词，就可能被召回。

接入 OpenViking 后，宽泛 query 的 after 数据是：

```text
before_context_tokens: 4376
after_context_tokens:  1661
before_noise_rate:     0.8333
after_noise_rate:      0.8333
after_load_context_ms: 125.9
```

也就是说，这个 query 下：

- token 少了。
- 延迟低了。
- 但噪声没降。

原因主要有几个：

1. query 太短，业务约束不够。
2. target_uri 只到 `viking://resources/tagent`，范围太大。
3. 没有强制 source_type 过滤。
4. 没有强制 domain/module 过滤。
5. OpenViking 会召回 overview 节点，overview 有时相关，但信息密度不一定够。
6. 当前噪声判断还是启发式，不是人工标注或 judge model。

所以这不是 OpenViking 一定没用，而是接入方式还比较粗。

## 更具体 query 后的情况

后面换了一个更具体的 query：

```text
检索XZ银行手机银行注册登录模块需求资料
```

这个 query 带上了：

```text
项目/领域：XZ银行
产品：手机银行
模块：注册登录
资料类型：需求资料
```

这次结果记录在：

```text
result/query_compare/context_xz_bank_mobile_register_login_requirements/compare.csv
```

结果：

```text
status:                 completed
context_count:          12
noise_context_rate:     0.0
overview_node_count:    6
detail_node_count:      6
estimated_context_tokens: 1616
load_context_total_ms:  107.62
```

这个结果比宽泛 query 好很多，至少说明一件事：OpenViking 不是不能降噪，而是 query、URI 和过滤策略要一起配合。

不过这里仍然有一个问题：召回结果里还有 6 个 overview 节点。

overview 节点不是一定没用，但如果后续生成测试用例，真正有价值的通常是需求正文、接口字段、业务规则、异常规则，而不是目录概览。所以后面应该考虑：

```text
限制 level
排除 .overview.md
优先 detail 节点
按 source_type 过滤
按 domain/module 过滤
```

## 当前 result 目录说明

当前和 OpenViking 实验相关的文件主要有：

```text
result/openviking_ingest_result.json
```

记录数据导入结果，主要看 total、succeeded、failed。

```text
result/openviking_observation_baseline_local.json
```

接入 OpenViking 前，本地 RAG/Memory 的观测基线。

```text
result/openviking_observation_after_openviking.json
```

接入 OpenViking 后，使用同一批 query 跑出来的观测结果。

```text
result/openviking_query_observation_records.json
```

按 query 维度记录的实验明细。

```text
result/query_compare/index.json
```

query 对比结果的索引文件。

```text
result/query_compare/summary.csv
```

所有 query 的简要对比汇总。

```text
result/query_compare/<query_name>/compare.json
result/query_compare/<query_name>/compare.csv
```

单个 query 的前后对比。

## 本地执行入口

`main.py` 现在只保留两条主链路：默认跑原生本地 RAG，传 `openviking` 时跑 OpenViking backend。

```bash
python main.py "检索登录相关需求资料"
python main.py openviking "检索登录相关需求资料"
```

导入、观测、报表仍然保留，但不再挂在 `main.py` 上，避免主入口变重：

```bash
python -m openviking.ingest --execute --wait
python -m observability.openviking_observation_run
python -m observability.openviking_compare_report
```

当前默认 query 可以通过环境变量改：

```bash
TAGENT_DEFAULT_QUERY="检索登录相关需求资料"
```

不带参数运行：

```bash
python main.py
```

会执行默认 query。

## 成本说明

这次本地实验的直接成本主要是：

- 本机 CPU、内存和磁盘。
- Docker 运行成本。
- 本地 embedding/indexing 的计算成本。

如果只是在本地 Docker 跑，并使用本地能力，通常没有额外云服务账单。但这不代表 OpenViking 生产使用一定免费。

生产环境可能产生几类成本：

1. OpenViking 服务部署成本  
   如果自己部署，就看机器、容器、存储、运维成本。如果使用云上的托管服务，就看云服务定价。

2. 模型服务成本  
   OpenViking 的语义处理、embedding、VLM 或 LLM 能力可能依赖外部模型服务。只要走外部 API，就可能按 token、请求量或资源用量计费。

3. API key 和账号体系  
   官方文档里 OpenViking Server 有 root key、user key、trusted/dev/api_key 几种认证模式。OpenViking 官网也提到可以从 Volcengine 控制台启用服务后获取 API Key。实际是否收费、按什么计费，需要看当时的火山引擎/OpenViking 服务定价和你选择的模型/部署方式。

4. 数据规模成本  
   文档越多，embedding、索引、存储、召回和重建索引的成本越高。这个成本不只是钱，也包括导入耗时、CPU、内存和运维复杂度。

所以这里先不写死一个金额。更实际的做法是：等生产方案明确后，用 Tagent 的观测指标统计每轮 query 的 token、召回数量、延迟，再结合 OpenViking 服务和模型服务的真实价格做成本表。

## 当前还没解决的问题

这次接入只是轻量实验，下面这些还没真正解决：

1. URI 设计还粗  
   当前统一挂在 `viking://resources/tagent` 下。后面应该考虑项目、领域、模块、版本、资料类型：

   ```text
   viking://resources/tagent/<project>/<domain>/<module>/<source_type>/<version>/<file>
   ```

2. metadata 没用起来  
   现在还没有稳定地把 `source_type`、`domain`、`module`、`project`、`version` 写进 OpenViking metadata，然后在查询时过滤。

3. overview 节点需要处理  
   当前会召回 `.overview.md`。后面要决定哪些场景要 overview，哪些场景只要明细节点。

4. 噪声判断还是启发式  
   现在的 `noise_context_rate` 不是人工金标，也不是 judge model。它可以做趋势观察，但不能当最终质量结论。

5. cross_project 指标需要重做  
   当前 `cross_project_context_rate` 会受到 URI 命名和 query 关键词影响，存在误判。

6. Memory 命中质量还没评  
   现在只记录命中数量和可追踪性，还没判断“这条 memory 对当前任务有没有用”。

7. 还没有生产级权限隔离  
   本地实验使用的是 default account 和 tagent user。真实环境需要按用户、项目、租户、团队做隔离。

8. 没有做长期压测  
   当前只是几十个文件和少量 query，不代表大规模文档、多用户并发、持续导入下的效果。



## 参考资料

- OpenViking Quick Start: https://github.com/volcengine/OpenViking/blob/main/docs/en/getting-started/02-quickstart.md
- OpenViking Authentication: https://docs.openviking.ai/en/guides/04-authentication
- OpenViking Server Deployment: https://docs.openviking.ai/en/guides/03-deployment
- OpenViking 官网: https://openviking.ai/
