# 回归影响分析技能

## 目标

当用户要分析需求变更、Bug 修复、API 变化或代码 diff 的回归影响时，使用这个技能。

## 触发条件

当主意图是 `REGRESSION_ANALYSIS` 时使用。

典型请求：

```text
分析这个改动影响哪些回归用例
这个需求变更需要回归哪些模块
根据这个 bug 修复给我回归范围
```

## 输入

```text
需求变更说明
Bug 修复说明
代码 diff 或分支
受影响接口
历史用例
历史 Bug
```

## 工作流程

1. 识别发生变化的行为。

2. 识别受影响的模块、API、数据和业务流程。

3. 检索相关历史用例和 Bug。

4. 按风险等级归类影响范围。

5. 推荐需要回归的用例。

6. 补充建议新增的用例。

## 计划接入的工具

```text
get_git_diff(branch)
search_existing_cases(feature)
search_related_bugs(keyword)
search_code(query)
get_api_contract(api_name)
```

## 输出约定

```json
{
  "change_summary": "...",
  "impacted_modules": [],
  "risk_level": "high/medium/low",
  "recommended_regression_cases": [],
  "new_case_suggestions": [],
  "evidence": [],
  "unknowns": []
}
```

## 质量检查

```text
影响范围是否有依据
是否引用历史用例或 Bug
是否区分风险等级
是否说明不确定项
是否避免泛泛建议全量回归
```

## 禁止事项

```text
不要在没有变更信息时编造影响范围
不要忽略接口兼容和数据兼容风险
```

## 兜底策略

如果缺少变更信息：

```text
要求用户补充需求变更、Bug 修复说明或代码 diff
```

如果没有找到历史用例：

```text
建议新增回归用例，并标明依据有限
```
