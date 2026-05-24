# 用例生成技能

## 目标

当用户希望基于需求、功能说明、PRD、API 文档、历史 Bug、已有用例或本地文件生成、补充、评审测试用例时，使用这个技能。

这个技能的目标是把项目上下文转成结构化、可执行、可追溯来源的测试用例。

## 触发条件

当主意图是 `CASE_GENERATION` 时使用。

典型请求：

```text
帮我给登录功能生成测试用例
根据桌面上的需求文档生成 case
基于这个 PRD 输出测试点
看一下这个接口文档，设计测试场景
根据历史 Bug 补充回归用例
```

如果用户表达比较间接，但目标是测试设计，也使用这个技能，例如：

```text
整理一下这个功能要测哪些点
这个需求覆盖点有哪些
帮我设计一下测试范围
```

如果用户主要是要执行测试、修自动化脚本、生成 Bug 报告或排查失败，不要使用这个技能。

## 输入

最小输入：

```text
用户要测试的功能、需求、文档、接口、Bug 或业务问题
```

可选输入：

```text
project / feature 限制
目标文件路径
期望输出数量
用例类型偏好
是否需要接口场景
是否需要历史 Bug 回归
是否需要自动化友好格式
```

如果用户提供了本地文件路径，能读取或解析时应先处理该文件，再生成用例。

## 所需上下文

从这些来源收集上下文：

```text
requirement：需求文档、PRD、验收标准、字段规则、流程规则
case：历史测试用例、测试点、已有覆盖路径
bug：历史缺陷、线上问题、回归风险
api：接口路径、请求字段、响应字段、错误码、鉴权约束
```

优先使用同项目上下文。除非用户明确要求跨项目参考，否则不要混入无关项目资料。

## 当前项目组件

使用当前项目里已有的组件：

```text
context.build_case_context(query)
prompts.promptcase.build_case_generation_prompt(context)
llm_client.call_llm(messages)
case_generator.generate_test_cases(query)
case_generator.parse_cases_response(response_text)
case_generator.validate_cases(cases)
```

当前输出路径：

```text
data/generated/generated_cases.json
```

## 工作流程

1. 先明确测试目标。

   识别用户想测试的对象：

   ```text
   功能 / 模块 / 文档 / API / Bug / 业务场景
   ```

2. 收集上下文。

   检索相关 chunk：

   ```text
   需求资料
   历史用例
   历史 Bug
   API 文档
   ```

3. 整理上下文。

   按资料类型组织上下文，至少保留：

   ```text
   chunk_id
   标题
   来源文件
   分数或检索类型
   project / feature
   tags
   内容
   ```

4. 显式或隐式地形成用例设计思路。

   生成结果必须覆盖：

   ```text
   正常流
   异常流
   边界值
   权限 / 鉴权
   接口场景
   历史 Bug 回归
   ```

   如果某类场景缺少上下文支撑，要在 `case_basis` 里说明限制。

5. 生成结构化用例。

   除非后续新增更细的提示词，否则使用 `prompts.promptcase`。

6. 解析并规范化输出。

   模型输出必须是 JSON。如果模型返回了 Markdown 代码块，解析前先去掉包裹标记。

7. 校验输出。

   至少要校验必填字段和列表字段类型。后续再接入专门的 用例校验器 做质量检查。

8. 保存并汇总。

   保存 JSON 结果，并汇总：

   ```text
   query
   case_count
   source_summary
   output_path
   warnings 或校验问题
   ```

## 输出结构

每条用例使用这个结构：

```json
{
  "case_id": "TC-001",
  "module": "模块名称",
  "title": "用例标题",
  "priority": "P0/P1/P2",
  "case_type": "正常流/异常流/边界值/权限/接口/历史Bug回归",
  "precondition": "前置条件",
  "steps": [
    "步骤1",
    "步骤2"
  ],
  "expected_result": "预期结果",
  "case_basis": "引用的需求/历史用例/Bug/API依据",
  "source_chunk_ids": ["chunk_id_1", "chunk_id_2"]
}
```

合法的 `priority`：

```text
P0
P1
P2
```

合法的 `case_type`：

```text
正常流
异常流
边界值
权限
接口
历史Bug回归
```

## 质量检查

接受结果前检查：

```text
是否覆盖核心需求
是否覆盖正常流
是否覆盖异常流
是否覆盖边界值
是否覆盖权限 / 鉴权
是否覆盖历史 Bug 回归
是否包含接口参数、错误码或鉴权场景
是否有重复 case
步骤是否可执行
预期结果是否明确
优先级是否合理
case_type 是否属于合法枚举
source_chunk_ids 是否真实存在
是否引用了无关项目上下文
```

## 禁止事项

不要：

```text
编造上下文中没有的业务规则
把通用测试建议写成已确认需求
引用无关项目资料作为主要依据
生成只有标题、没有步骤和预期的空泛 case
输出解释性段落替代 JSON
泄露敏感信息
```

## 兜底策略

如果上下文不足：

```text
生成有限 case
在 case_basis 标注“上下文不足，仅给出通用测试方向”
把缺失上下文写入 warnings 或 summary
```

如果检索结果混入无关内容：

```text
优先使用同 project / feature 的 chunk
降低无关 source 的权重
必要时要求用户补充项目或文件范围
```

如果模型输出不是合法 JSON：

```text
保存 原始响应
返回解析错误
后续可触发重试或 JSON 修复流程
```

如果生成结果没有通过校验：

```text
不要直接接受结果
进入 用例校验器
标记具体失败项
必要时重新生成或局部修复
```

## 示例

用户输入：

```text
根据 xx租房项目的房源筛选需求生成测试用例
```

预期行为：

```text
1. 检索 xx租房项目相关需求
2. 检索房源筛选历史用例
3. 检索房源相关历史 Bug
4. 检索相关接口资料
5. 生成 8-15 条结构化测试用例
6. 标注 source_chunk_ids
7. 输出保存路径和 source_summary
```

预期结果摘要：

```text
intent: CASE_GENERATION
skill: case_generation
case_count: 8-15
output: data/generated/generated_cases.json
```
