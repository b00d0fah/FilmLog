# 群晖 NAS 部署与更新说明

本文档说明 FilmLog 在群晖 NAS 上的推荐部署、更新、备份和回滚方式。当前项目适合使用 DSM 的 Container Manager 运行，默认 Web 服务端口为 `8000`。

## 当前推荐部署信息

```text
项目目录：/volume1/docker/filmlog
容器名称：filmlog
Web 端口：8000
访问地址：http://NAS_IP:8000
局域网示例：http://10.77.190.181:8000
```

DSM 管理页面通常占用 `5000` 端口，所以 FilmLog 推荐使用 `8000` 或其他独立端口。

## 方案 A：Container Manager / Docker Compose

这是推荐方案。

1. 在 NAS 上创建目录：

```bash
mkdir -p /volume1/docker/filmlog
cd /volume1/docker/filmlog
```

2. 上传项目源码到该目录，并准备运行数据：

```text
.env
filmlog.db
static/uploads/
static/thumbs/
static/index_sheets/
```

首次部署如果没有数据库，可以创建空文件：

```bash
touch filmlog.db
mkdir -p static/uploads static/thumbs static/index_sheets
```

3. 构建并启动：

```bash
docker compose up -d --build
```

4. 查看容器状态：

```bash
docker ps --filter name=filmlog
docker logs --tail 80 filmlog
```

5. 浏览器访问：

```text
http://NAS_IP:8000
```

## 方案 B：Python 虚拟环境

如果没有安装 Container Manager，可以直接用 Python 和 Waitress 运行。

```bash
cd /volume1/docker/filmlog
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
FILMLOG_HOST=0.0.0.0 FILMLOG_PORT=8000 FILMLOG_DEBUG=0 waitress-serve --host=0.0.0.0 --port=8000 wsgi:app
```

后台运行示例：

```bash
cd /volume1/docker/filmlog
. venv/bin/activate
FILMLOG_HOST=0.0.0.0 FILMLOG_PORT=8000 FILMLOG_DEBUG=0 nohup waitress-serve --host=0.0.0.0 --port=8000 wsgi:app > filmlog.log 2>&1 &
```

也可以把上述命令加入 DSM“任务计划”的开机触发脚本。

## DSM 反向代理

如果希望使用域名或 HTTPS，可在 DSM 控制面板中配置反向代理：

```text
来源协议：HTTPS 或 HTTP
来源主机：你的域名或 NAS 局域网主机名
来源端口：自定义端口
目标协议：HTTP
目标主机：127.0.0.1
目标端口：8000
```

## 更新已部署项目

更新原则：代码可以覆盖，运行数据必须保留。

需要保留的运行数据：

```text
.env
filmlog.db
static/uploads/
static/thumbs/
static/index_sheets/
```

推荐更新流程：

1. 在 NAS 上备份当前代码和配置：

```bash
cd /volume1/docker/filmlog
tar --exclude './filmlog.db' \
    --exclude './.env' \
    --exclude './static/uploads' \
    --exclude './static/thumbs' \
    --exclude './static/index_sheets' \
    -czf /volume1/docker/filmlog_code_backup_$(date +%Y%m%d%H%M%S).tar.gz .
```

2. 从本地上传不含运行数据的代码包。

打包时应排除：

```text
.git
__pycache__/
*.pyc
.env
filmlog.db
*.db
*.sqlite
*.sqlite3
static/uploads/
static/thumbs/
static/index_sheets/
assets/fonts/*.ttc
assets/fonts/*.ttf
assets/fonts/*.otf
*apiKey*.csv
```

3. 在 NAS 上解包到 `/volume1/docker/filmlog`。

4. 重建并启动容器：

```bash
cd /volume1/docker/filmlog
mkdir -p static/uploads static/thumbs static/index_sheets
docker compose up -d --build filmlog
```

5. 验证：

```bash
docker ps --filter name=filmlog
docker logs --tail 80 filmlog
```

浏览器打开：

```text
http://NAS_IP:8000
```

## 备份清单

完整备份至少包含：

```text
.env
filmlog.db
static/uploads/
static/thumbs/
static/index_sheets/
```

推荐先停止服务再备份：

```bash
cd /volume1/docker/filmlog
docker compose down
tar -czf /volume1/docker/filmlog_data_backup_$(date +%Y%m%d%H%M%S).tar.gz .env filmlog.db static/uploads static/thumbs static/index_sheets
docker compose up -d
```

如果只做代码更新，通常不需要备份全部照片；但数据库和 `.env` 仍建议定期备份。

## 回滚

如果更新后容器无法启动：

1. 查看日志：

```bash
docker logs --tail 120 filmlog
```

2. 停止容器：

```bash
cd /volume1/docker/filmlog
docker compose down
```

3. 解压最近的代码备份：

```bash
cd /volume1/docker/filmlog
tar -xzf /volume1/docker/filmlog_code_backup_YYYYMMDDHHMMSS.tar.gz
```

4. 重新启动：

```bash
docker compose up -d --build
```

## 常见问题

### 端口打不开

检查容器是否运行、端口是否被占用、防火墙是否允许 `8000`：

```bash
docker ps --filter name=filmlog
```

### AI 功能不可用

检查 `.env` 中是否配置了 `DASHSCOPE_API_KEY`，并确认 `QWEN_BASE_URL`、模型名称和账户额度可用。未配置 API Key 不影响基础照片管理功能。

### 中文索引图字体异常

Docker 镜像会安装 `fonts-noto-cjk`。如果直接用 Python 虚拟环境运行，请确保系统中有可用中文字体，或参考 `assets/fonts/README.md` 放置字体文件。

### 构建时报 `.dockerignore` 异常

Synology 的 Docker 构建环境对 `.dockerignore` 中的非 ASCII 忽略规则兼容性较差。`.dockerignore` 中应只保留必要的英文路径和通配规则。
