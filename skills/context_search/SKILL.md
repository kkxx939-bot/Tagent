# 上下文检索技能

## 目标

当用户要检索需求、历史用例、Bug、API 或 chunk 上下文时，使用这个技能。

## 触发条件

当主意图是 `CONTEXT_SEARCH` 时使用。

典型请求：

```text
查一下租房相关需求
检索登录接口相关资料
找一下历史 Bug
看看这个功能有没有历史用例
```

## 输入

```text
query
source_type
project / feature 限制
top_k
检索模式
```

## 工作流程

1. 解析查询内容和可选的资料类型。

2. 选择检索模式。

   当前模式：

   ```text
   BM25
   混合检索：BM25 + 向量检索 + rerank
   ```

3. 检索相关 chunk。

4. 按资料类型分组。

5. 返回来源文件、chunk ID、标题、分数和内容预览。

## 当前项目组件

```text
RAGwork.searchfile.search_knowledge
RAGwork.hybrid_search.hybrid_search
context.build_case_context
```

这些是项目内部检索组件，不是 Executor 的外部 tool。Planner 需要通过 `load_context` 调用 `context_search`，不要额外规划 `call_tool`。

## 输出约定

```json
{
  "query": "...",
  "results": [
    {
      "chunk_id": "...",
      "source_type": "...",
      "source_file": "...",
      "title": "...",
      "score": 0.0,
      "content": "..."
    }
  ],
  "source_summary": {}
}
```

## 质量检查

```text
结果是否包含 chunk_id
结果是否包含 source_file
相关性依据是否清楚
是否混入无关项目
是否需要 project / feature 过滤
```

## 禁止事项

```text
不要把检索结果改写成已确认需求
不要隐藏低相关性风险
```

## 兜底策略

如果结果太少：

```text
降低 min_score
放宽查询词
让用户补充更具体的关键词
```

如果结果噪声太多：

```text
按 source_type 过滤
按 project / feature 过滤
可用时使用 rerank
```
