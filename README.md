# FilmLog 胶片摄影信息管理系统

FilmLog 是一个面向个人胶片摄影流程的 Web 信息管理系统。系统以“一卷胶片”为核心，将胶卷档案、冲扫记录、照片导入、评分标签、AI 辅助分析、索引图生成和长期统计复盘整合在同一个工作流中。

本项目当前已适配本地运行和群晖 NAS 部署。线上数据默认保存在 SQLite 数据库和 `static/` 数据目录中，适合作为个人胶片摄影档案库长期使用。


## 主要功能

- 胶卷档案：记录标题、胶卷型号、ISO、相机、镜头、画幅、拍摄状态、拍摄日期、地点和备注。
- 冲扫信息：记录冲扫店、冲扫工艺、迫冲/减冲、扫描仪、文件格式、冲扫日期和评价。
- 批量导入：支持 JPG、JPEG、PNG、WEBP、TIF、TIFF，保存原图并自动生成缩略图。
- 照片整理：按实际导入顺序自动编号，支持单张照片编辑、删除、下载和精选标记。
- 评分体系：从技术、构图、色彩、情绪四个维度进行 1.0-10.0、0.5 步进评分，并计算最终评分。
- 标签管理：支持自定义标签、自动标签建议、标签筛选和统计页标签黑名单。
- 批量操作：支持照片多选、批量下载、批量 AI 分析。
- 胶片索引图：按整卷照片生成 contact sheet 风格索引图，便于归档和分享。
- AI 辅助分析：接入阿里云百炼 / DashScope 兼容接口，生成照片描述、推荐标签、评分建议和整卷复盘。
- 观片统计：按胶卷、相机、冲扫店、标签、精选作品、高分作品和年度最佳作品进行复盘。
- NAS 部署：支持 Docker Compose / Container Manager 部署，适合存放大量冲扫原图。

## 技术栈

- 后端：Python、Flask、Waitress
- 数据库：SQLite
- 图像处理：Pillow
- AI 接口：OpenAI SDK 兼容接口，默认指向 DashScope
- 前端：Jinja2 模板、原生 CSS、少量原生 JavaScript
- 部署：Docker Compose、群晖 Container Manager、Python 虚拟环境

## 目录结构

```text
FilmLog_project/
├── app.py                  # Flask 路由与页面控制
├── config.py               # 环境变量、数据库路径、上传限制
├── db.py                   # SQLite 初始化、迁移和查询封装
├── utils.py                # 图片保存、缩略图、评分、索引图工具
├── qwen_service.py         # 千问 / DashScope AI 调用封装
├── wsgi.py                 # 生产部署入口
├── FilmLog 本地启动器.bat       # Windows 本地一键启动入口
├── LOCAL_DEPLOY.md         # 小白用户本地部署说明
├── scripts/
│   └── Start-FilmLog.ps1   # Windows 自动检测、安装依赖和启动脚本
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── deploy_synology.ps1     # Python 虚拟环境部署辅助脚本
├── templates/              # Jinja2 页面模板
├── static/
│   ├── css/style.css
│   ├── uploads/            # 原图，运行数据
│   ├── thumbs/             # 缩略图，运行数据
│   └── index_sheets/       # 胶片索引图，运行数据
├── assets/
│   ├── film_strips/        # 索引图底片条模板与 135 齿孔模板
│   └── fonts/              # 可选字体覆盖目录，仅提交 README 和 .gitkeep
└── uml/                    # PlantUML 图源文件
```

## 本地运行

Windows 推荐方式：

双击项目根目录里的 `FilmLog 本地启动器.bat`。脚本会自动检查 Python、创建 `.venv`、安装依赖、生成 `.env`，然后打开浏览器访问 FilmLog。

首次运行和日常使用都使用同一个入口：

- 第一次运行：自动检查 Python 3.10+、创建虚拟环境、安装依赖、生成本地配置。
- 日常启动：复用已有 `.venv` 和 `.env`，依赖缺失或 `requirements.txt` 变化时自动补装。
- API Key：如果项目根目录存在阿里云百炼导出的 API Key CSV，脚本会自动写入 `.env`。
- 未配置 API Key：系统仍可启动，但自动评分、照片分析和整卷复盘不可用。

更详细的小白版说明见 [LOCAL_DEPLOY.md](LOCAL_DEPLOY.md)。

Windows 手动方式：

```powershell
cd FilmLog_project
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

macOS / Linux：

```bash
cd FilmLog_project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

默认访问：

```text
http://127.0.0.1:5000
```

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改：

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
QWEN_TEXT_MODELS=qwen-plus,qwen3.6-flash,qwen3.5-flash,qwen-turbo
QWEN_VISION_MODELS=qwen-vl-plus,qwen3-vl-plus,qwen3-vl-flash,qwen-vl-max
QWEN_ENABLE_VISION=1
```

说明：

- `FILMLOG_DB_PATH` 可使用相对路径或绝对路径。
- `FILMLOG_MAX_CONTENT_MB` 控制上传请求大小，默认 600 MB。
- Windows 一键启动脚本会自动扫描项目根目录中的 API Key CSV。支持文件名包含 `apiKey`、`apikey`、`dashscope`、`qwen` 或 `api-key` 的 `.csv` 文件，并读取其中的 `apiKey` 字段；如有 `openAiCompatible` 字段，也会写入 `QWEN_BASE_URL`。
- 未配置 `DASHSCOPE_API_KEY` 时，系统仍可使用胶卷管理、照片导入、手动评分、标签、下载、索引图和统计功能；自动评分、照片分析和整卷复盘不可用。
- `QWEN_TEXT_MODELS` 和 `QWEN_VISION_MODELS` 是候选模型列表，主模型不可用时会尝试后续模型。

## Docker 运行

```bash
docker compose up -d --build
```

默认访问：

```text
http://127.0.0.1:8000
```

Compose 会把以下运行数据挂载在项目目录中：

```text
filmlog.db
static/uploads/
static/thumbs/
static/index_sheets/
```

`assets/film_strips/` 是索引图生成所需的模板资产，应随源码一起部署。`assets/fonts/` 只是可选字体覆盖目录，Docker 镜像已安装 `fonts-noto-cjk`，通常不需要提交或部署字体文件。

## 胶片索引图模板

索引图模板放在 `assets/film_strips/`：

```text
assets/film_strips/
├── 135/
│   ├── sprocket_strip.png
│   └── kodak-gc-400/
│       ├── 1-6.png
│       ├── 7-12.png
│       └── ...
└── 120/
```

135 模板规则：

- 每个胶片类型一个目录，目录名使用小写 ASCII 和连字符，例如 `kodak-gc-400`。
- 每条底片模板最多嵌入 6 张照片，文件名按帧段命名：`1-6.png`、`7-12.png`、`13-18.png`，直到 `37-42.png`。
- `assets/film_strips/135/sprocket_strip.png` 是 135 模板共用齿孔叠加层。
- 生成时先嵌入照片，再叠加齿孔；超过 42 张照片会拒绝生成。

## 群晖 NAS 部署状态

当前项目可部署在群晖 NAS 的 Container Manager 中，推荐目录：

```text
/volume1/docker/filmlog
```

推荐访问端口：

```text
http://NAS_IP:8000
```

详细部署、更新、备份和回滚步骤见 [NAS_DEPLOY.md](NAS_DEPLOY.md)。

## 使用流程

1. 在“显影”页面创建胶卷档案，填写胶卷、机身、镜头、画幅、日期和地点。
2. 在胶卷详情页补充冲扫信息。
3. 批量上传冲扫照片，系统保存原图并生成缩略图。
4. 编辑单张照片，补充拍摄参数、备注、标签和评分。
5. 需要时执行单张或批量 AI 分析，生成描述、标签和评分建议。
6. 将优秀照片标记为精选，或下载单张/多张原图。
7. 生成整卷胶片索引图。
8. 在“观片”页面查看胶卷、相机、冲扫店、标签和高分作品统计。

## 数据备份与迁移

至少备份：

```text
.env
filmlog.db
static/uploads/
static/thumbs/
static/index_sheets/
```

索引图模板资产 `assets/film_strips/` 建议随代码一起备份或纳入版本库；运行数据备份不包含模板时，恢复后也必须从代码包补齐该目录。

建议在备份或迁移前先停止容器，避免 SQLite 正在写入：

```bash
docker compose down
```

恢复后重新启动：

```bash
docker compose up -d --build
```

## UML

PlantUML 源文件位于 `uml/`：

- `use_case.puml`：系统用例。
- `class_diagram.puml`：核心数据模型和服务关系。
- `sequence_diagram.puml`：照片导入、AI 分析和索引图生成流程。

## 发布前检查

- 不提交 `.env`、数据库、上传原图、缩略图、已生成索引图和 API Key CSV。
- 不提交 `assets/fonts/` 下的字体文件；公开仓库只保留 `README.md` 和 `.gitkeep`。
- 确认 `assets/film_strips/` 中的底片条模板和 `sprocket_strip.png` 已纳入代码包。
- 推送前运行 `python -m py_compile app.py utils.py db.py`。

## 许可

本项目开放源码，但禁止商业使用。允许个人、学习、研究、审阅和其他非商业用途使用、复制、修改和分发。商业使用需事先获得版权所有者书面许可。详见 [LICENSE](LICENSE)。

