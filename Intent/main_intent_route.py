"""主意图识别。

这一层只负责判断用户输入应该进入哪条主流程。
第一版使用规则打分，不调用模型。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

try:
    from Intent.llm_intent_router import classify_main_intent_with_llm
except ModuleNotFoundError:
    from llm_intent_router import classify_main_intent_with_llm


QUERY = "登录接口返回 500，有 traceId=abc123，帮我看一下"

DEFAULT_SUB_INTENT = "NONE"

NEXT_ACTIONS = {
    "CASE_GENERATION": "generate_cases",
    "FAILURE_TRIAGE": "start_failure_triage",
    "AUTOMATION_WRITING": "plan_automation_writing",
    "AUTOMATION_FAILURE_FIX": "start_automation_failure_fix",
    "EXECUTION_ASSISTANT": "assist_case_execution",
    "BUG_REPORT_GENERATION": "generate_bug_report",
    "REGRESSION_ANALYSIS": "analyze_regression_impact",
    "CONFIG_HELP": "answer_config_help",
    "CONTEXT_SEARCH": "search_context",
    "RESULT_REVIEW": "review_generated_result",
    "PROJECT_QA": "answer_project_question",
    "OUT_OF_SCOPE": "report_capability_gap",
}

MAIN_INTENT_RULES = [
    {
        "intent": "AUTOMATION_FAILURE_FIX",
        "base": 0.48,
        "strong_keywords": (
            "自动化失败",
            "自动化 case 失败",
            "自动化case失败",
            "脚本失败",
            "断言失败",
            "等待超时",
            "定位不到",
            "找不到元素",
            "playwright报错",
            "selenium报错",
        ),
        "keywords": (
            "selector",
            "locator",
            "playwright",
            "selenium",
            "appium",
            "pytest",
            "cypress",
            "脚本",
            "case 失败",
            "case失败",
        ),
        "negative_keywords": ("生成自动化", "写自动化", "自动化代码"),
    },
    {
        "intent": "FAILURE_TRIAGE",
        "base": 0.42,
        "strong_keywords": (
            "登录不上",
            "请求失败",
            "接口失败",
            "系统异常",
            "返回500",
            "返回 500",
            "traceid",
            "trace id",
            "requestid",
            "request id",
            "打不开",
            "挂了",
            "case 挂了",
            "测试用例挂了",
            "测试用例 挂了",
        ),
        "keywords": (
            "失败",
            "报错",
            "错误",
            "异常",
            "500",
            "timeout",
            "超时",
            "看一下",
            "排查",
            "帮我看看",
        ),
        "negative_keywords": ("测试用例", "测试点", "生成用例", "用例设计", "回归测试用例"),
    },
    {
        "intent": "CONFIG_HELP",
        "base": 0.36,
        "strong_keywords": ("api key", "llm_api_key", "环境变量", "base_url"),
        "keywords": (
            "apikey",
            "config",
            "配置",
            "deepseek",
            "模型",
        ),
    },
    {
        "intent": "AUTOMATION_WRITING",
        "base": 0.4,
        "strong_keywords": (
            "生成自动化",
            "写自动化",
            "自动化代码",
            "自动化脚本",
            "生成 playwright",
            "写 playwright",
        ),
        "keywords": (
            "playwright",
            "selenium",
            "appium",
            "pytest",
            "cypress",
        ),
        "negative_keywords": ("断言失败", "等待超时", "定位不到", "找不到元素", "脚本失败"),
    },
    {
        "intent": "CASE_GENERATION",
        "base": 0.4,
        "strong_keywords": (
            "生成用例",
            "写用例",
            "生成测试用例",
            "写测试用例",
            "测试用例",
            "测试点",
            "用例设计",
            "回归测试用例",
        ),
        "keywords": (
            "生成case",
            "生成 case",
            "case生成",
            "case 生成",
            "覆盖场景",
            "测试场景",
        ),
    },
    {
        "intent": "EXECUTION_ASSISTANT",
        "base": 0.38,
        "strong_keywords": (
            "执行用例",
            "跑用例",
            "执行 case",
            "执行case",
            "跑测试",
            "执行测试",
            "重启服务",
            "重启测试环境",
        ),
        "keywords": ("测试执行", "执行一下", "跑一下", "执行结果", "测试结果", "重启", "测试环境"),
    },
    {
        "intent": "BUG_REPORT_GENERATION",
        "base": 0.38,
        "strong_keywords": ("生成bug报告", "生成 bug 报告", "写bug报告", "写 bug 报告", "缺陷报告"),
        "keywords": ("提bug", "提 bug", "bug报告", "bug 报告", "缺陷单", "问题单"),
    },
    {
        "intent": "REGRESSION_ANALYSIS",
        "base": 0.38,
        "strong_keywords": ("回归影响分析", "回归范围", "影响哪些回归", "改动影响"),
        "keywords": ("回归", "影响分析", "影响哪些", "风险范围", "回归用例", "变更影响"),
    },
    {
        "intent": "CONTEXT_SEARCH",
        "base": 0.34,
        "strong_keywords": ("相关资料", "相关需求", "查一下", "找一下", "检索一下"),
        "keywords": (
            "检索",
            "召回",
            "chunk",
            "rag",
            "bm25",
            "向量",
            "rerank",
            "上下文",
            "需求",
            "资料",
        ),
    },
    {
        "intent": "RESULT_REVIEW",
        "base": 0.34,
        "strong_keywords": ("generated_cases", "查看结果", "生成结果", "输出文件", "结果文件"),
        "keywords": (
            "保存在哪里",
            "保存到哪里",
            "质量怎么样",
            "评审",
            "review",
        ),
    },
    {
        "intent": "PROJECT_QA",
        "base": 0.3,
        "strong_keywords": ("下一步", "怎么设计", "解释一下"),
        "keywords": (
            "流程",
            "为什么",
            "逻辑",
            "怎么做",
            "是什么",
        ),
    },
]


@dataclass
class MainIntentResult:
    intent: str
    sub_intent: str
    confidence: float
    is_ready: bool
    evidence: list[str]
    missing_context: list[str]
    next_action: str
    requires_permission: bool
    sensitive_risk: list[str]
    alternative_intents: list[dict[str, object]]
    extracted_context: dict[str, object]
    secondary_result: dict[str, object] | None


def recognize_main_intent(user_input: str) -> dict[str, object]:
    """识别主意图，返回统一结构。"""
    text = normalize_text(user_input)
    if not text:
        return asdict(build_result("OUT_OF_SCOPE", 0.0, ["输入为空"], [], text))

    llm_result = classify_main_intent_with_llm(user_input=user_input)
    if is_usable_llm_result(llm_result):
        intent = str(llm_result["intent"])
        confidence = float(llm_result["confidence"])
        evidence = [f"LLM识别：{item}" for item in llm_result.get("evidence", [])]
        if llm_result.get("reason"):
            evidence.append(f"LLM理由：{llm_result['reason']}")
        alternatives = normalize_llm_alternatives(llm_result.get("alternative_intents"))
        if is_case_and_automation_query(text):
            intent = "CASE_GENERATION"
            confidence = max(confidence, 0.86)
            evidence.append("识别到先生成 case，再生成自动化脚本的复合任务")
            if not any(item.get("intent") == "AUTOMATION_WRITING" for item in alternatives):
                alternatives.insert(
                    0,
                    {
                        "intent": "AUTOMATION_WRITING",
                        "confidence": 0.72,
                        "evidence": ["复合任务后半段需要生成自动化脚本"],
                    },
                )
        return asdict(build_result(intent, confidence, evidence, alternatives, text))

    if is_case_and_automation_query(text):
        evidence = build_rule_fallback_evidence(
            {
                "intent": "CASE_GENERATION",
                "confidence": 0.86,
                "evidence": ["识别到先生成 case，再生成自动化脚本的复合任务"],
            },
            llm_result,
        )
        return asdict(
            build_result(
                "CASE_GENERATION",
                0.86,
                evidence,
                [
                    {
                        "intent": "AUTOMATION_WRITING",
                        "confidence": 0.72,
                        "evidence": ["复合任务后半段需要生成自动化脚本"],
                    }
                ],
                text,
            )
        )

    scored = score_intent_rules(text)
    if scored:
        intent = str(scored[0]["intent"])
        confidence = float(scored[0]["confidence"])
        evidence = build_rule_fallback_evidence(scored[0], llm_result)
        alternatives = [
            {
                "intent": item["intent"],
                "confidence": item["confidence"],
                "evidence": item["evidence"],
            }
            for item in scored[1:4]
        ]
        return asdict(build_result(intent, confidence, evidence, alternatives, text))

    evidence = build_out_of_scope_evidence(llm_result)
    return asdict(build_result("OUT_OF_SCOPE", 0.3, evidence, [], text))


def is_usable_llm_result(llm_result: dict[str, object]) -> bool:
    return bool(llm_result.get("is_valid")) and str(llm_result.get("intent") or "OUT_OF_SCOPE") != "OUT_OF_SCOPE"


def normalize_llm_alternatives(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    alternatives = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        alternatives.append(
            {
                "intent": item.get("intent"),
                "confidence": item.get("confidence"),
                "evidence": [item.get("reason")] if item.get("reason") else [],
            }
        )
    return alternatives


def build_rule_fallback_evidence(rule_result: dict[str, object], llm_result: dict[str, object]) -> list[str]:
    evidence = ["模型不可用或低置信，使用规则兜底"]
    if llm_result.get("error"):
        evidence.append(f"模型错误：{llm_result['error']}")
    elif llm_result.get("intent") == "OUT_OF_SCOPE":
        evidence.append("模型返回 OUT_OF_SCOPE")
    evidence.extend(str(item) for item in rule_result.get("evidence", []))
    return evidence


def build_out_of_scope_evidence(llm_result: dict[str, object]) -> list[str]:
    evidence = ["模型和规则都没有得到可执行的测试主意图"]
    if llm_result.get("error"):
        evidence.append(f"模型错误：{llm_result['error']}")
    elif llm_result.get("intent") == "OUT_OF_SCOPE":
        evidence.append("模型返回 OUT_OF_SCOPE")
    return evidence


def score_intent_rules(text: str) -> list[dict[str, object]]:
    scored = []
    for rule in MAIN_INTENT_RULES:
        strong_matches = match_keywords(text, rule.get("strong_keywords", ()))
        weak_matches = match_keywords(text, rule.get("keywords", ()))
        negative_matches = match_keywords(text, rule.get("negative_keywords", ()))
        if not strong_matches and not weak_matches:
            continue

        score = float(rule["base"]) + len(strong_matches) * 0.22 + len(weak_matches) * 0.08
        score -= len(negative_matches) * 0.18
        if score <= 0:
            continue

        evidence = [f"命中强关键词：{keyword}" for keyword in strong_matches]
        evidence.extend(f"命中关键词：{keyword}" for keyword in weak_matches)
        if negative_matches:
            evidence.extend(f"降权关键词：{keyword}" for keyword in negative_matches)

        scored.append(
            {
                "intent": rule["intent"],
                "confidence": round(min(score, 0.95), 2),
                "evidence": evidence,
            }
        )

    scored.sort(key=lambda item: (item["confidence"], priority_of_intent(str(item["intent"]))), reverse=True)
    return scored


def priority_of_intent(intent: str) -> int:
    priority = {
        "AUTOMATION_FAILURE_FIX": 90,
        "CASE_GENERATION": 80,
        "AUTOMATION_WRITING": 75,
        "FAILURE_TRIAGE": 70,
        "REGRESSION_ANALYSIS": 65,
        "BUG_REPORT_GENERATION": 60,
        "EXECUTION_ASSISTANT": 55,
    }
    return priority.get(intent, 10)


def build_result(
    intent: str,
    confidence: float,
    evidence: list[str],
    alternative_intents: list[dict[str, object]],
    text: str,
) -> MainIntentResult:
    extracted_context = extract_main_context(text)
    return MainIntentResult(
        intent=intent,
        sub_intent=DEFAULT_SUB_INTENT,
        confidence=confidence,
        is_ready=is_ready_by_intent(intent, extracted_context),
        evidence=evidence,
        missing_context=missing_context_by_intent(intent, extracted_context),
        next_action=NEXT_ACTIONS[intent],
        requires_permission=False,
        sensitive_risk=[],
        alternative_intents=alternative_intents,
        extracted_context=extracted_context,
        secondary_result=None,
    )


def is_ready_by_intent(
    intent: str,
    extracted_context: dict[str, object],
) -> bool:
    if intent == "OUT_OF_SCOPE":
        return False
    if intent == "FAILURE_TRIAGE":
        return bool(extracted_context.get("trace_id"))
    if intent == "AUTOMATION_FAILURE_FIX":
        return False
    if intent in {"CASE_GENERATION", "AUTOMATION_WRITING", "REGRESSION_ANALYSIS"}:
        return bool(extracted_context.get("target"))
    return True


def missing_context_by_intent(
    intent: str,
    extracted_context: dict[str, object],
) -> list[str]:
    if intent == "CASE_GENERATION" and not extracted_context.get("target"):
        return ["需要说明要生成哪个功能/需求的测试用例"]
    if intent == "AUTOMATION_WRITING" and not extracted_context.get("target"):
        return ["需要说明要把哪条用例或哪个功能生成自动化代码"]
    if intent == "REGRESSION_ANALYSIS" and not extracted_context.get("target"):
        return ["需要说明本次变更、需求或代码影响范围"]
    if intent == "FAILURE_TRIAGE":
        missing = ["环境", "错误现象", "接口状态码/response", "traceId/requestId", "是否所有账号都失败"]
        if extracted_context.get("trace_id"):
            missing.remove("traceId/requestId")
        return missing
    if intent == "AUTOMATION_FAILURE_FIX":
        return ["失败日志", "自动化框架", "失败用例", "截图/trace/控制台日志"]
    if intent == "OUT_OF_SCOPE":
        return ["当前输入不属于明确的测试任务，或缺少足够信息进入测试流程"]
    return []


def normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def match_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def is_case_and_automation_query(text: str) -> bool:
    has_case = any(keyword in text for keyword in ("case", "用例", "测试点", "测试用例"))
    has_case_generation = has_case and any(keyword in text for keyword in ("生成", "写", "设计", "整理"))
    has_automation = any(keyword in text for keyword in ("自动化", "playwright", "selenium", "pytest", "appium", "cypress"))
    return has_case_generation and has_automation


def extract_main_context(text: str) -> dict[str, object]:
    target_markers = (
        "登录",
        "注册",
        "房源",
        "筛选",
        "订单",
        "支付",
        "退款",
        "转账",
        "贷款",
        "接口",
        "用例",
        "case",
        "需求",
        "改动",
        "变更",
    )
    frameworks = [name for name in ("playwright", "selenium", "appium", "pytest", "cypress") if name in text]
    return {
        "target": [marker for marker in target_markers if marker in text],
        "frameworks": frameworks,
        "trace_id": extract_trace_or_request_id(text),
    }


def extract_trace_or_request_id(text: str) -> str | None:
    patterns = [
        r"(?i)(?:traceid|trace_id|trace id)\s*[:= ]\s*([a-z0-9._\-]+)",
        r"(?i)(?:requestid|request_id|request id)\s*[:= ]\s*([a-z0-9._\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return None


def print_intent(user_input: str) -> None:
    result = recognize_main_intent(user_input)
    print(f"query: {user_input}")
    for key, value in result.items():
        print(f"{key}: {value}")


def main() -> None:
    examples = [
        QUERY,
        "帮我给租房筛选生成测试用例",
        "把这条用例生成 Playwright 自动化脚本",
        "generated_cases.json 保存在哪里",
        "这个项目下一步应该做什么",
    ]
    for example in examples:
        print_intent(example)
        print()


if __name__ == "__main__":
    main()
