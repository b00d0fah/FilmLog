# 可选字体目录

FilmLog 在生成胶片索引图时需要可用字体来渲染中文标题、胶卷信息和照片编号。Docker 镜像会安装开源 `fonts-noto-cjk`，通常不需要额外放置字体。

如果直接在 Windows 或其他系统上用 Python 运行，Pillow 可以使用系统字体，例如：

```text
C:\Windows\Fonts\msyh.ttc
```

如需自定义字体，可把字体文件放在本目录，但请注意：

- 不要提交商业字体或授权不明确的字体。
- 不要把系统字体复制到公开仓库。
- `.gitignore` 和 `.dockerignore` 默认会排除 `*.ttc`、`*.ttf`、`*.otf`。

推荐做法是只提交本说明文件和 `.gitkeep`，字体文件由部署环境自行提供。
