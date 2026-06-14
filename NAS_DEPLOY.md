# 群晖 NAS 部署说明

以下路径和端口可按实际情况调整。DSM 管理页通常占用 `5000`，FilmLog 建议使用 `8000`。

## 方案 A：Python 虚拟环境

1. 在 NAS 上准备目录：

```bash
mkdir -p /volume1/docker/filmlog
```

2. 上传项目文件、`filmlog.db` 和 `static/` 数据目录。

3. 安装依赖并启动：

```bash
cd /volume1/docker/filmlog
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
FILMLOG_HOST=0.0.0.0 FILMLOG_PORT=8000 FILMLOG_DEBUG=0 waitress-serve --host=0.0.0.0 --port=8000 wsgi:app
```

4. 浏览器访问：

```text
http://NAS_IP:8000
```

## 方案 B：DSM 反向代理

如果希望使用 DSM 的域名或 HTTPS：

- 来源：自定义域名或端口。
- 目标协议：HTTP。
- 目标主机：`127.0.0.1`。
- 目标端口：`8000`。

## 方案 C：Container Manager

如果 NAS 已安装 Container Manager，可上传整个 `FilmLog_project` 目录后执行：

```bash
cd /volume1/docker/filmlog
docker compose up -d --build
```

容器会映射 `8000:8000`，并把数据库和照片目录挂载在项目目录内，便于备份和迁移。

## 迁移现有数据

必须迁移：

```text
filmlog.db
static/uploads/
static/thumbs/
static/index_sheets/
.env
```

建议先停止 FilmLog，再复制数据，避免 SQLite 正在写入。

## 后台运行建议

可以在 DSM 任务计划中添加“开机触发”的用户自定义脚本，内容类似：

```bash
cd /volume1/docker/filmlog
source venv/bin/activate
FILMLOG_HOST=0.0.0.0 FILMLOG_PORT=8000 FILMLOG_DEBUG=0 nohup waitress-serve --host=0.0.0.0 --port=8000 wsgi:app > filmlog.log 2>&1 &
```
