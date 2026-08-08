"""Deterministic quality checks plus optional AI quality/title assistance."""

from __future__ import annotations

import re
from typing import Any

from .llm import LLMClient, LLMError
from .utils import html_to_text


def basic_quality(title: str, body_html: str) -> dict[str, Any]:
    title = str(title or "").strip()
    body_text = html_to_text(body_html)
    title_problems: list[str] = []
    dirty_content: list[str] = []
    completeness: list[str] = []
    if not title:
        title_problems.append("标题为空")
    if len(title) > 80:
        title_problems.append("标题超过 80 字")
    if re.search(r"(?:\.\.\.|…|，|,|：|:)$", title):
        title_problems.append("标题疑似截断或未完结")
    for pattern, reason in (
        (r"(?:扫码|点击购买|优惠活动|立即购买|加微信)", "正文疑似包含营销语句"),
        (r"(?:版权归|本文转自|未经许可不得转载)", "正文疑似包含版权声明"),
        (r"(?:图：|摄影：|图片：|▲)\s*[^<]{0,80}$", "正文疑似残留图注"),
    ):
        if re.search(pattern, body_text, re.I | re.M):
            dirty_content.append(reason)
    if len(body_text) < 30:
        completeness.append("正文少于 30 字")
    if re.search(r"(?:\.\.\.|…)$", body_text):
        completeness.append("正文疑似以省略号截断")
    hard = bool(title_problems or completeness)
    soft = bool(dirty_content)
    return {
        "mode": "basic",
        "pass": not hard and not soft,
        "reject": hard,
        "issues": {
            "title_problems": title_problems,
            "dirty_content": dirty_content,
            "completeness_problems": completeness,
        },
        "reason": "内容正常" if not (hard or soft) else "；".join((title_problems + dirty_content + completeness)[:2]),
        "score": 0 if hard else (50 if soft else 100),
        "action_hint": "REJECT" if hard else ("HUMAN_REVIEW" if soft else "READY"),
    }


def run_quality(title: str, body_html: str, llm: LLMClient | None = None) -> dict[str, Any]:
    result = basic_quality(title, body_html)
    if llm is None:
        return result
    prompt = f"""你是懂球帝内容审核编辑，只检查硬性问题，不评价价值或可信度。
标题：{title}
正文：{html_to_text(body_html)}
输出 JSON：{{"pass":true,"reject":false,"issues":{{"title_problems":[],"dirty_content":[],"completeness_problems":[]}},"reason":"20字以内"}}
标题截断、正文为空/明显截断应 reject=true；只有广告、图注、版权残留时 pass=false、reject=false。"""
    try:
        ai_result = llm.chat_json(prompt)
        if isinstance(ai_result, dict):
            ai_result["mode"] = "ai"
            ai_result.setdefault("issues", result["issues"])
            ai_result.setdefault("reason", "")
            ai_result["score"] = 0 if ai_result.get("reject") else (50 if not ai_result.get("pass") else 100)
            ai_result["action_hint"] = "REJECT" if ai_result.get("reject") else ("HUMAN_REVIEW" if not ai_result.get("pass") else "READY")
            return ai_result
    except LLMError as exc:
        result["mode"] = "basic_fallback"
        result["ai_error"] = str(exc)
    return result


def check_and_fix_title(title: str, body_html: str, llm: LLMClient | None = None) -> tuple[str, dict[str, Any]]:
    original = str(title or "").strip()
    result: dict[str, Any] = {
        "mode": "basic",
        "is_incomplete": not bool(original) or bool(re.search(r"(?:\.\.\.|…|，|,|：|:)$", original)),
        "fixed_title": original,
        "reason": "标题为空或疑似未完结" if not original else "未发现明显截断",
    }
    if llm is None or not original:
        return original, result
    prompt = f"""请判断并在必要时补全体育新闻标题。
原标题：{original}
正文摘要：{html_to_text(body_html)[:500]}
输出 JSON：{{"is_incomplete":true,"fixed_title":"补全后的标题","reason":"15字以内"}}。完整标题必须原样返回，补全标题不超过60字。"""
    try:
        ai_result = llm.chat_json(prompt)
        if isinstance(ai_result, dict):
            fixed = str(ai_result.get("fixed_title") or original).strip()
            result.update(ai_result, mode="ai", fixed_title=fixed)
            if ai_result.get("is_incomplete") and fixed:
                return fixed[:60], result
    except LLMError as exc:
        result["ai_error"] = str(exc)
    return original, result

