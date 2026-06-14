"""从阿里云百炼导出的 apiKey CSV 创建本地 .env 文件。

用法：
python setup_env_from_csv.py dashscope-api-key.csv

注意：脚本不会把 API Key 打印到屏幕，只会写入项目根目录下的 .env。
"""
from __future__ import annotations

import csv
import os
import sys

DEFAULT_TEXT_MODEL = "qwen-plus"
DEFAULT_VISION_MODEL = "qwen-vl-plus"
DEFAULT_TEXT_MODELS = "qwen-plus,qwen3.6-flash,qwen3.5-flash,qwen-turbo"
DEFAULT_VISION_MODELS = "qwen-vl-plus,qwen3-vl-plus,qwen3-vl-flash,qwen-vl-max"


def read_key_value_csv(path: str) -> dict:
    data = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                data[row[0].strip()] = row[1].strip()
    return data


def main() -> int:
    if len(sys.argv) < 2:
        print("请提供 CSV 文件路径，例如：python setup_env_from_csv.py dashscope-api-key.csv")
        return 1
    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"找不到文件：{csv_path}")
        return 1
    data = read_key_value_csv(csv_path)
    api_key = data.get("apiKey", "")
    base_url = data.get("openAiCompatible") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if not api_key:
        print("CSV 中没有找到 apiKey 字段。")
        return 1

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"DASHSCOPE_API_KEY={api_key}\n")
        f.write(f"QWEN_BASE_URL={base_url}\n")
        f.write(f"QWEN_TEXT_MODEL={DEFAULT_TEXT_MODEL}\n")
        f.write(f"QWEN_VISION_MODEL={DEFAULT_VISION_MODEL}\n")
        f.write(f"QWEN_TEXT_MODELS={DEFAULT_TEXT_MODELS}\n")
        f.write(f"QWEN_VISION_MODELS={DEFAULT_VISION_MODELS}\n")
        f.write("QWEN_ENABLE_VISION=1\n")
    print("已生成 .env。API Key 已写入本地配置文件，未在屏幕显示。")
    print(f"接口地址：{base_url}")
    print(f"文本模型：{DEFAULT_TEXT_MODEL}；视觉模型：{DEFAULT_VISION_MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
