# Optional Fonts

FilmLog looks for fonts in this directory first when generating index sheets.

Do not commit commercial or system fonts. In Docker, the image installs the open-source `fonts-noto-cjk` package so Chinese text can render without bundling local font files.

If you run the app directly on Windows, Pillow can also use system fonts such as Microsoft YaHei from `C:\Windows\Fonts`.
