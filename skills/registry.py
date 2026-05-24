"""按 intent 查找 Skill 的注册表。"""

from __future__ import annotations

from skills.automation_failure_fix_skill import AUTOMATION_FAILURE_FIX_SKILL
from skills.automation_writing_skill import AUTOMATION_WRITING_SKILL
from skills.bug_report_skill import BUG_REPORT_SKILL
from skills.case_generation_skill import CASE_GENERATION_SKILL
from skills.config_help_skill import CONFIG_HELP_SKILL
from skills.context_search_skill import CONTEXT_SEARCH_SKILL
from skills.failure_triage_skill import FAILURE_TRIAGE_SKILL
from skills.project_qa_skill import PROJECT_QA_SKILL
from skills.regression_analysis_skill import REGRESSION_ANALYSIS_SKILL
from skills.result_review_skill import RESULT_REVIEW_SKILL


SKILLS_BY_INTENT = {
    skill.intent: skill
    for skill in (
        CASE_GENERATION_SKILL,
        FAILURE_TRIAGE_SKILL,
        AUTOMATION_WRITING_SKILL,
        AUTOMATION_FAILURE_FIX_SKILL,
        BUG_REPORT_SKILL,
        REGRESSION_ANALYSIS_SKILL,
        CONTEXT_SEARCH_SKILL,
        RESULT_REVIEW_SKILL,
        PROJECT_QA_SKILL,
        CONFIG_HELP_SKILL,
    )
}


def get_skill(intent: str):
    """按 intent 返回对应的 SkillSpec；不支持时返回 None。"""
    return SKILLS_BY_INTENT.get(intent)


def list_skills() -> list[dict[str, object]]:
    """以字典形式返回所有已注册的 Skill。"""
    return [skill.to_dict() for skill in SKILLS_BY_INTENT.values()]
