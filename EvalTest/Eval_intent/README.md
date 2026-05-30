# 意图评测

`Eval_intent` 用来评测 Tagent 的主意图识别、ready 判断和关键实体抽取。

默认禁用 LLM，评测稳定的规则兜底和 query 标准化链路；需要评真实模型时使用 `--allow-llm`。

## 运行

跑 smoke：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py
```

跑 full：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --suite full_eval
```

跑指定 case：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --suite full_eval --case-id intent_case_login_001
```

打开 LLM：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --allow-llm
```

## 报告

默认每次运行都会写入：

```text
EvalTest/Eval_intent/report/
  latest.json          # 最近一次完整报告
  history.jsonl        # 每次运行的一行摘要历史
  trend.csv            # 趋势数据，方便导入表格或看板
  trend.svg            # 轻量趋势图
  runs/*.json          # 每次运行的完整报告
```

关闭 report 写入：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --no-report
```

指定 report 目录：

```bash
/opt/anaconda3/envs/Tagent/bin/python EvalTest/Eval_intent/run_eval.py --report-dir /tmp/intent_eval_report
```

## 样本格式

```json
{
  "id": "intent_case_login_001",
  "query": "根据登录需求生成测试用例",
  "expect": {
    "intent": "CASE_GENERATION",
    "is_ready": true,
    "next_action": "generate_cases",
    "target_contains": ["登录"],
    "missing_context_contains": []
  },
  "tags": ["case_generation", "ready"]
}
```

## 指标

- `intent_accuracy`: 主意图是否正确。
- `ready_accuracy`: `is_ready` 是否正确。
- `next_action_accuracy`: 下一步动作是否正确。
- `entity_accuracy`: target/framework/trace/source/force 等实体断言通过率。
- `missing_context_accuracy`: 缺失上下文断言通过率。
- `case_pass_rate`: 整条 case 所有断言是否通过。
- `confusion_matrix`: 期望 intent 和实际 intent 的混淆矩阵。
