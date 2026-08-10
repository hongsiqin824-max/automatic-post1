# 素材分发工作台

这是一个与旧项目完全独立的首版系统，目录为 `automatic post1`。它不修改上游素材接口，不读取实验目录；开放平台的 token 会保存在本地 SQLite 中，不会写回旧项目。

## 当前链路

```text
配置 source + 后台 tab ID
        ↓
GET /v1/url_ingest/ai_materials
        ↓
SQLite 入库，material_key = url:v1:<source_url 规范化后的 SHA-256>
        ↓
基础质检（可选 AI 质检）
        ↓
标题检查（可选 AI 补全）
        ↓
固定 archive_level=B
        ↓
开放平台签名 + OAuth 授权
        ↓
POST admin-archive-createarticle，固定 status=0
        ↓
懂球帝草稿
```

`channels` 只按标签 ID 数组保存、去重和格式清理；首版没有标签语义校验，但数据库和详情页已保留标签校验入口所需字段。`translate_body` 和 `dqd_litpic` 的相对图片路径原样保存并原样提交，不在本项目补 CDN。

## 启动

```bash
cd "/Users/demo/Desktop/automatic/automatic post1"
cp .env.example .env
# 编辑 .env，至少填写 MATERIAL_API_KEY；草稿联调前填写 DQD_OPEN_APPID / DQD_OPEN_APPSECRET，`DQD_OPEN_REDIRECT_URI` 默认指向本地回调
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

不使用虚拟环境时，可以在这个目录里直接执行：

```bash
pip3 install -r requirements.txt
python3 run.py
```

浏览器打开 <http://127.0.0.1:8900>。

不想使用 `.env` 时，也可以直接在 shell 中导出同名环境变量。`.env` 已加入 `.gitignore`。

## 页面操作

- “来源与栏目”：新增或编辑 source，填写懂球帝后台栏目 ID。栏目未配置时素材仍会入库，但状态为 `栏目未配置`，不会发创建请求。
- “仅拉取”：按最近小时数请求每个启用 source，接口分页会自动继续拉取，不创建草稿。
- “一键拉取并创建草稿”：只处理本次拉回的素材，拉取后立刻执行基础质检、标题检查、栏目映射，并对通过检查的素材创建懂球帝草稿。
- “处理待处理”：执行基础质检、标题检查和栏目映射，不创建草稿。
- “开放平台授权”：先点“发起授权”，浏览器会跳到懂球帝授权页，授权完成后自动回到工作台并保存 token。
- “创建草稿”：对已处理完成、栏目已映射、创建失败或授权恢复后的素材批量创建或重试创建草稿；请求只带 `status=0`，同时会自动带上开放平台签名和 `Authorization: Bearer ...`。
- “详情”：查看 material_key、原始 URL、上游/懂球帝文章 ID、标签 ID、质检 JSON、正文和状态时间线。

## 必须由你提供的联调信息

1. 轮换后的素材接口 `MATERIAL_API_KEY`，并确认它绑定的 `caller`（默认 `editor.ai_materials`）。你之前发出的旧 SK 已暴露，不应继续使用。
2. 创建文章开放平台的授权信息：`DQD_OPEN_APPID`、`DQD_OPEN_APPSECRET`、`DQD_OPEN_REDIRECT_URI`。如果平台已经给你做了授权回调白名单，系统就可以自己跳转授权，不需要你手工维护 token。
3. 每个 source 对应的后台栏目 ID。无需发给我，可以直接在页面“来源与栏目”中维护；也可以填 `MATERIAL_API_SOURCES` 作为首次可选 source。
4. （可选）草稿链接模板：`DQD_DRAFT_URL_TEMPLATE`。默认值已经指向懂球帝草稿编辑页，创建成功后会在页面里直接显示可点击链接。

## 暂不需要提供的信息

- 不需要上游增加 `material_id`；`source_url` 哈希已经是本地稳定业务主键，`archive_id=0` 只代表上游还没有懂球帝文章。
- 不需要图片 CDN 前缀或图片下载逻辑。
- 不需要标签名称；当前按接口返回的 `channels` 整数 ID 保存。
- 不需要手工提供 `access_token` / `refresh_token`；系统会通过授权页自动换取并刷新。
- 不需要发布接口；首期只创建草稿。已有草稿改 `status` 的正式接口文档仍需后续补充。

## 状态说明

`已接收 → 质检中 → 标题检查中 → 待创建草稿 → 创建草稿中 → 草稿已创建` 是正常路径。缺少 source-tab 映射会进入 `栏目未配置`；上游 `archive_id>0` 会进入 `上游已有文章`；开放平台没授权会进入 `开放平台待授权`，授权过期会进入 `开放平台授权过期`；硬性质量问题会进入 `质检拒绝`，软性脏内容会进入 `待人工复核`；接口错误会进入 `创建失败`。

## 测试

```bash
PYTHONPYCACHEPREFIX=/private/tmp/material-workflow-pycache python3 -m unittest discover -s tests -v
```

测试只使用临时 SQLite，不访问任何线上接口。
