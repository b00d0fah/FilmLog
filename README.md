# FilmLog 胶片摄影信息管理系统

FilmLog 是一个面向个人胶片摄影流程的本地 Web 系统。它以“胶卷”为核心，记录拍摄、冲扫、照片导入、评分、标签、索引图和复盘统计，并可接入千问视觉模型辅助分析照片。

> 开源仓库不包含个人照片、SQLite 数据库、`.env`、API Key 或本地字体文件。部署前请复制 `.env.example` 并自行配置。

## 功能

- 胶卷档案：胶卷型号、ISO、相机、镜头、画幅、地点、状态和备注。
- 冲扫信息：冲扫店、工艺、迫冲/减冲、扫描仪、文件格式和评价。
- 照片管理：批量导入 JPG/PNG/WEBP/TIFF，保存原图并生成缩略图。
- 评分与标签：技术、构图、色彩、情绪四项评分，支持精选标记和自定义标签。
- 胶片索引图：生成模拟冲扫店底片袋的高清胶片联系表，竖幅照片自动转为横幅。
- 统计复盘：按胶卷、相机、冲扫店、标签和高分作品进行汇总。
- AI 分析：调用千问模型生成照片描述、推荐标签、评分建议和整卷复盘。

## 目录结构

```text
FilmLog_project/
├── app.py                  # Flask 路由和页面控制
├── config.py               # 环境变量与部署配置
├── db.py                   # SQLite 初始化和查询封装
├── utils.py                # 图片、标签、评分和索引图工具
├── qwen_service.py         # 千问 API 调用封装
├── ai_classifier.py        # 本地轻量标签候选
├── wsgi.py                 # 生产部署入口
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── templates/              # Jinja2 页面
├── static/
│   ├── css/style.css
│   ├── uploads/            # 原图
│   ├── thumbs/             # 缩略图
│   └── index_sheets/       # 索引图
└── uml/                    # PlantUML 源文件
```

运行数据包括 `filmlog.db` 和 `static/uploads`、`static/thumbs`、`static/index_sheets`。迁移项目时需要一起复制。

## 本地运行

```bash
cd FilmLog_project
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

浏览器打开 `http://127.0.0.1:5000`。

macOS/Linux 激活虚拟环境使用：

```bash
source venv/bin/activate
```

## 配置

复制 `.env.example` 为 `.env`，按需填写：

```env
FILMLOG_SECRET_KEY=change-me
FILMLOG_HOST=127.0.0.1
FILMLOG_PORT=5000
FILMLOG_DEBUG=1
FILMLOG_MAX_CONTENT_MB=600
FILMLOG_DB_PATH=filmlog.db

DASHSCOPE_API_KEY=
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TEXT_MODEL=qwen-plus
QWEN_VISION_MODEL=qwen-vl-plus
QWEN_ENABLE_VISION=1
```

如果没有配置 `DASHSCOPE_API_KEY`，系统仍可使用照片管理、评分、标签、索引图和统计功能，AI 功能会提示未配置。

## Docker 运行

```bash
docker compose up -d --build
```

默认访问地址：

```text
http://127.0.0.1:8000
```

容器会把 `filmlog.db`、`static/uploads/`、`static/thumbs/` 和 `static/index_sheets/` 挂载在项目目录中，便于备份和迁移。

## 生产运行

Windows 或 Linux 均可使用 Waitress：

```bash
waitress-serve --host=0.0.0.0 --port=8000 wsgi:app
```

群晖 DSM 默认使用 5000 端口，建议 FilmLog 使用 8000 或其他端口，再通过 DSM 反向代理绑定域名或局域网路径。

## UML

PlantUML 源文件位于 `uml/`：

- `use_case.puml`：系统用例。
- `class_diagram.puml`：核心数据模型和服务关系。
- `sequence_diagram.puml`：照片导入、AI 分析和索引图生成流程。

## 迁移清单

部署或备份时至少保留：

- `filmlog.db`
- `.env`
- `static/uploads/`
- `static/thumbs/`
- `static/index_sheets/`

不要把 `.env`、数据库和照片目录提交到公开仓库。

## 开源许可

本项目使用 MIT License。详见 `LICENSE`。
