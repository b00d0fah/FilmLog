# FilmLog 本地一键启动

这份说明面向不熟悉编程的 Windows 用户。正常情况下，只需要双击项目根目录里的 `FilmLog 本地启动器.bat`。

## 第一次使用

1. 解压项目压缩包。
2. 进入项目文件夹。
3. 如果你要使用 AI 自动评分、照片分析和整卷复盘，把阿里云百炼导出的 API Key CSV 文件放到这个项目文件夹里。文件名建议保留 `apiKey` 字样。
4. 双击 `FilmLog 本地启动器.bat`。
5. 如果电脑没有 Python，脚本会提示是否自动安装。输入 `Y` 后回车。
6. 等待脚本完成环境检查、依赖安装、API Key 检测和系统启动。
7. 浏览器会自动打开：

```text
http://127.0.0.1:5000
```

第一次运行会创建这些本地文件：

```text
.env              本地配置
.venv/            Python 运行环境
filmlog.db        本地数据库，首次进入系统后自动创建
filmlog_start.log 启动日志
```

这些文件保存了本地运行状态，不要随意删除。备份或迁移时至少保留 `.env`、`filmlog.db` 和 `static/` 目录里的上传图片、缩略图、索引图。

## 以后每天使用

1. 双击 `FilmLog 本地启动器.bat`。
2. 浏览器自动打开 FilmLog。
3. 使用结束后，关闭启动窗口即可停止系统。

脚本会复用第一次创建好的环境。发现依赖缺失时会自动补装。

## AI 功能

不配置 API Key 也可以正常使用胶卷管理、照片导入、评分、标签、下载、索引图和统计功能。

如果项目根目录里有阿里云百炼导出的 API Key CSV 文件，例如文件名里包含 `apiKey`、`apikey`、`dashscope`、`qwen` 或 `api-key`，双击启动时会自动读取并写入 `.env`。脚本不会把 API Key 显示到屏幕上。

自动识别的 CSV 字段：

```text
apiKey              必填，写入 DASHSCOPE_API_KEY
openAiCompatible    可选，写入 QWEN_BASE_URL
```

识别成功后，启动窗口会显示已找到 API Key 文件，但不会显示 Key 内容。

如果没有自动识别，但你要使用 AI 分析：

1. 用记事本打开项目根目录的 `.env`。
2. 找到这一行：

```env
DASHSCOPE_API_KEY=
```

3. 在等号后填入你的 DashScope API Key。
4. 保存文件。
5. 关闭启动窗口后重新双击 `FilmLog 本地启动器.bat`。

没有配置 API Key 时，启动窗口会提示：未配置大模型 API，无法使用自动评分、照片分析和整卷复盘功能。这个提示不会阻止系统启动。

## 常见问题

### 提示端口 5000 已被占用

打开 `.env`，把：

```env
FILMLOG_PORT=5000
```

改成：

```env
FILMLOG_PORT=5001
```

保存后重新双击 `FilmLog 本地启动器.bat`。

### 依赖安装失败

通常是网络问题。确认能访问互联网后重新双击 `FilmLog 本地启动器.bat`。

如果仍失败，可以右键开始菜单打开 PowerShell，进入项目目录后运行：

```powershell
scripts\Start-FilmLog.ps1 -Repair
```

### 浏览器没有自动打开

启动窗口里会显示访问地址，手动复制到浏览器即可。

默认地址是：

```text
http://127.0.0.1:5000
```

### Windows 提示脚本不能运行

请双击 `FilmLog 本地启动器.bat`，不要直接双击 `.ps1` 文件。bat 会用临时方式绕过本次启动的脚本限制。

