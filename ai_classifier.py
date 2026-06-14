"""
轻量图片自动分类模块。

说明：
1. 为了保证课程演示环境能在普通个人电脑上稳定运行，本模块默认不依赖大型深度学习模型；
2. 它会读取图片的亮度、饱和度、色彩比例、画幅方向和文件名关键词，自动生成候选标签；
3. 如果后续想升级为真正的 CLIP / YOLO / ViT 识别，只需要替换 classify_image() 函数即可，数据库和页面不用改。
"""
from __future__ import annotations

import os
from collections import Counter
from typing import List
from PIL import Image, ImageStat, ImageOps

KEYWORD_TAGS = {
    "portrait": "人像",
    "people": "人像",
    "person": "人像",
    "girl": "人像",
    "boy": "人像",
    "street": "街拍",
    "city": "城市",
    "building": "建筑",
    "architecture": "建筑",
    "landscape": "风景",
    "mountain": "山景",
    "sea": "海边",
    "beach": "海边",
    "sunset": "日落",
    "night": "夜景",
    "food": "美食",
    "cat": "宠物",
    "dog": "宠物",
    "flower": "花卉",
    "travel": "旅行",
}


def _clamp_tags(tags: List[str], max_count: int = 6) -> List[str]:
    seen = set()
    result = []
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
        if len(result) >= max_count:
            break
    return result


def classify_image(image_path: str) -> List[str]:
    """返回自动识别的中文标签列表。"""
    tags: List[str] = []

    filename = os.path.basename(image_path).lower()
    for key, tag in KEYWORD_TAGS.items():
        if key in filename:
            tags.append(tag)

    try:
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            w, h = img.size
            if w > h * 1.15:
                tags.append("横构图")
            elif h > w * 1.15:
                tags.append("竖构图")
            else:
                tags.append("方构图")

            # 缩小后分析色彩，避免大图占用内存。
            img.thumbnail((160, 160))
            stat = ImageStat.Stat(img)
            r, g, b = stat.mean[:3]
            brightness = (r + g + b) / 3

            # 计算粗略饱和度。
            pixels = list(img.getdata())
            sample_count = min(len(pixels), 8000)
            if sample_count == 0:
                return _clamp_tags(tags)
            step = max(1, len(pixels) // sample_count)
            sampled = pixels[::step]
            sat_values = []
            color_counter = Counter()
            for pr, pg, pb in sampled:
                mx, mn = max(pr, pg, pb), min(pr, pg, pb)
                sat = 0 if mx == 0 else (mx - mn) / mx
                sat_values.append(sat)
                if pb > pr * 1.12 and pb > pg * 1.05:
                    color_counter["blue"] += 1
                if pg > pr * 1.05 and pg > pb * 1.05:
                    color_counter["green"] += 1
                if pr > pg * 1.08 and pr > pb * 1.08:
                    color_counter["red"] += 1
                if pr > 150 and pg > 110 and pb < 100:
                    color_counter["warm"] += 1
            avg_sat = sum(sat_values) / len(sat_values)
            total = len(sampled)

            if brightness < 70:
                tags.append("夜景")
            elif brightness > 205 and avg_sat < 0.2:
                tags.append("高调")
            if avg_sat < 0.12:
                tags.append("黑白")
            elif avg_sat > 0.42:
                tags.append("高饱和")

            blue_ratio = color_counter["blue"] / total
            green_ratio = color_counter["green"] / total
            warm_ratio = color_counter["warm"] / total

            if green_ratio > 0.24:
                tags.append("风景")
            if blue_ratio > 0.26:
                tags.append("天空/海边")
            if warm_ratio > 0.18:
                tags.append("日落/暖色")

            # 胶片照片常见的整体色彩倾向标签。
            if r > g + 8 and r > b + 8:
                tags.append("暖色调")
            elif b > r + 8 and b > g + 5:
                tags.append("冷色调")
    except Exception:
        tags.append("待人工标记")

    if not tags:
        tags.append("待人工标记")
    return _clamp_tags(tags)
