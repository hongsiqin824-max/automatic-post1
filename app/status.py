"""Canonical status names used by the UI and database."""

STATUS_LABELS = {
    "RECEIVED": "已接收",
    "QUALITY_CHECKING": "质检中",
    "TITLE_CHECKING": "标题检查中",
    "NEEDS_REVIEW": "待人工复核",
    "TAB_UNMAPPED": "栏目未配置",
    "READY_TO_CREATE": "待创建草稿",
    "DRAFT_CREATING": "创建草稿中",
    "DRAFT_CREATED": "草稿已创建",
    "ALREADY_HAS_ARCHIVE": "上游已有文章",
    "CREATE_ERROR": "创建失败",
    "REJECTED": "质检拒绝",
}

TERMINAL_STATUSES = {"DRAFT_CREATED", "ALREADY_HAS_ARCHIVE", "REJECTED"}

