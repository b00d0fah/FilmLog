from __future__ import annotations

import os
import re
import uuid
from math import floor
from typing import Iterable, List
from PIL import Image, ImageDraw, ImageFont, ImageOps
from werkzeug.utils import secure_filename
from db import execute, query_all, query_one
from time_utils import local_timestamp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
THUMB_DIR = os.path.join(STATIC_DIR, "thumbs")
INDEX_DIR = os.path.join(STATIC_DIR, "index_sheets")
FILM_STRIP_ASSET_DIR = os.path.join(BASE_DIR, "assets", "film_strips")
INDEX_135_MAX_PHOTOS = 42
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "tif", "tiff"}
SCORE_MIN = 1.0
SCORE_MAX = 10.0
SCORE_STEP = 0.5
SCORE_DEFAULT = 5.5
SCORE_OPTIONS = [SCORE_MIN + i * SCORE_STEP for i in range(int((SCORE_MAX - SCORE_MIN) / SCORE_STEP) + 1)]
SCORE_TOTAL_MAX = SCORE_MAX * 4
SCORE_PART_WEIGHTS = (0.25, 0.28, 0.20, 0.27)
SCORE_PART_COLUMNS = (
    "tech_score",
    "composition_score",
    "color_score",
    "emotion_score",
)

# 135 index visual tuning parameters. Adjust these when refining the film-strip
# simulation: title area, frame positions, sprocket placement, typography, and strip spacing.
INDEX_135_LAYOUT = {
    "frames_per_strip": 6,
    "sheet_bg": (250, 250, 246),
    "sheet_margin_x": 0,
    "sheet_margin_bottom": 0,
    "header_h": 480,
    "header_bg": (16, 16, 16),
    "header_divider_y": 468,
    "header_divider_fill": (236, 236, 232),
    "header_divider_w": 5,
    "header_brand_text": "FilmLog",
    "header_brand_x": 72,
    "header_brand_y": 78,
    "header_brand_font_size": 112,
    "header_right_w": 1540,
    "header_right_x_offset": 72,
    "header_title_y": 64,
    "header_meta_y": 152,
    "header_date_y": 210,
    "header_extra_y": 264,
    "header_title_font_size": 72,
    "header_meta_font_size": 42,
    "header_date_font_size": 42,
    "header_extra_font_size": 42,
    "header_note_font_size": 42,
    "header_line_gap": 28,
    "header_title_fill": (246, 246, 242),
    "header_meta_fill": (190, 190, 182),
    "header_date_fill": (150, 150, 142),
    "photo_x": 26,
    "photo_y": 110,
    "photo_w": 720,
    "photo_h": 480,
    "photo_step_x": 746,
    "sprocket_x": 28,
    "sprocket_top_y": 40,
    "sprocket_bottom_y": 600,
    "sheet_strip_gap": 25,
    "label_font_size": 22,
    "frame_font_size": 24,
    "top_text_y": 10,
    "bottom_text_y": 668,
    "frame_text_offset_x": 12,
    "film_text_offset_x": 98,
    "text_fill": (238, 238, 224),
    "empty_frame_fill": (0, 0, 0),
}

INDEX_SHEET_DEFAULTS = {
    "show_header": True,
    "show_header_text": False,
    "header_height": INDEX_135_LAYOUT["header_h"],
    "header_bg_color": "#101010",
    "header_brand": "FilmLog",
    "header_title": "",
    "header_note": "",
    "film_info": "",
    "strip_template": "",
    "border_size": 35,
    "border_color": "#ffffff",
    "strip_gap": INDEX_135_LAYOUT["sheet_strip_gap"],
}


def ensure_dirs():
    for path in [UPLOAD_DIR, THUMB_DIR, INDEX_DIR]:
        os.makedirs(path, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def relative_static_path(abs_path: str) -> str:
    return os.path.relpath(abs_path, STATIC_DIR).replace("\\", "/")


def save_photo_file(file_storage, roll_id: int, frame_number: int) -> int:
    """保存原图，生成缩略图，写入照片记录，并返回 photo_id。"""
    ensure_dirs()
    original_name = secure_filename(file_storage.filename or "photo.jpg")
    ext = original_name.rsplit(".", 1)[1].lower()
    unique_name = f"roll{roll_id}_frame{frame_number}_{uuid.uuid4().hex[:10]}.{ext}"

    roll_upload_dir = os.path.join(UPLOAD_DIR, f"roll_{roll_id}")
    roll_thumb_dir = os.path.join(THUMB_DIR, f"roll_{roll_id}")
    os.makedirs(roll_upload_dir, exist_ok=True)
    os.makedirs(roll_thumb_dir, exist_ok=True)

    image_abs = os.path.join(roll_upload_dir, unique_name)
    file_storage.save(image_abs)

    file_size_mb = os.path.getsize(image_abs) / 1024 / 1024
    thumb_abs = os.path.join(roll_thumb_dir, unique_name.rsplit(".", 1)[0] + ".jpg")

    width, height = 0, 0
    try:
        with Image.open(image_abs) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            img.thumbnail((520, 520))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(thumb_abs, "JPEG", quality=82, optimize=True)
    except Exception:
        # 如果图片损坏，仍保留原始文件，但使用空路径占位。
        thumb_abs = image_abs

    image_rel = relative_static_path(image_abs)
    thumb_rel = relative_static_path(thumb_abs)
    photo_id = execute(
        """
        INSERT INTO photos(
            roll_id, frame_number, original_filename, image_path, thumb_path,
            file_size_mb, width, height,
            tech_score, composition_score, color_score, emotion_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            roll_id,
            frame_number,
            original_name,
            image_rel,
            thumb_rel,
            file_size_mb,
            width,
            height,
            SCORE_DEFAULT,
            SCORE_DEFAULT,
            SCORE_DEFAULT,
            SCORE_DEFAULT,
        ),
    )
    return photo_id


def get_tags_for_photo(photo_id: int) -> List[str]:
    rows = query_all(
        """
        SELECT t.name FROM tags t
        JOIN photo_tags pt ON pt.tag_id = t.id
        WHERE pt.photo_id = ?
        ORDER BY t.name
        """,
        (photo_id,),
    )
    return [r["name"] for r in rows]


def set_photo_tags(photo_id: int, tags: Iterable[str], append: bool = False):
    tag_names = []
    for raw in tags:
        for part in str(raw).replace("，", ",").split(","):
            name = part.strip().replace("#", "")
            if name in {"胶片", "胶片感", "胶片质感"}:
                continue
            if name in {"黑白/低饱和", "低饱和"}:
                name = "黑白"
            if name and name not in tag_names:
                tag_names.append(name)

    if not append:
        execute("DELETE FROM photo_tags WHERE photo_id = ?", (photo_id,))

    for name in tag_names:
        tag = query_one("SELECT id FROM tags WHERE name = ?", (name,))
        if tag:
            tag_id = tag["id"]
        else:
            tag_id = execute("INSERT INTO tags(name) VALUES (?)", (name,))
        execute(
            "INSERT OR IGNORE INTO photo_tags(photo_id, tag_id) VALUES (?, ?)",
            (photo_id, tag_id),
        )


def normalize_score(value, default: float = SCORE_DEFAULT) -> float:
    try:
        value = float(value)
    except Exception:
        value = default
    value = round(value / SCORE_STEP) * SCORE_STEP
    return round(max(SCORE_MIN, min(SCORE_MAX, value)), 1)


def _normalized_score_parts(scores) -> List[float]:
    normalized = [normalize_score(score) for score in scores]
    if len(normalized) < len(SCORE_PART_COLUMNS):
        normalized.extend([SCORE_DEFAULT] * (len(SCORE_PART_COLUMNS) - len(normalized)))
    return normalized[: len(SCORE_PART_COLUMNS)]


def final_score_from_parts(scores) -> float:
    normalized = _normalized_score_parts(scores)
    low = min(normalized)
    high = max(normalized)
    spread = high - low
    mean = sum(normalized) / len(normalized)
    strong_count = sum(1 for score in normalized if score >= 7.0)
    weak_count = sum(1 for score in normalized if score <= 4.0)

    score = sum(
        score * weight for score, weight in zip(normalized, SCORE_PART_WEIGHTS)
    )

    if weak_count:
        score -= 0.10 * weak_count
    if low <= 2.5:
        score -= 0.35
    elif low <= 4.0 and high >= 7.5:
        score -= 0.16

    if spread <= 1.0 and mean >= 7.0:
        score += 0.10
    elif spread >= 4.0:
        score -= 0.16 + (spread - 4.0) * 0.03
    elif spread >= 2.5:
        score -= 0.06

    if high >= 8.0 and strong_count >= 3 and low >= 5.5:
        score += 0.08

    # Small deterministic profile adjustment reduces ties between photos with the same mean.
    tech, composition, color, emotion = normalized
    score += (composition - tech) * 0.025
    score += (emotion - color) * 0.020
    score += (high + low - mean * 2) * 0.010

    if low <= 2.5:
        score = min(score, 6.20)
    elif low <= 4.0:
        score = min(score, 7.60)
    elif low <= 5.5 and high >= 8.5:
        score = min(score, 8.80)

    score = max(1.0, min(10.0, score))
    return floor(score * 100 + 0.500000001) / 100


def _sql_score_part(alias: str, column: str) -> str:
    prefix = f"{alias}." if alias else ""
    return f"MIN({SCORE_MAX}, MAX({SCORE_MIN}, COALESCE({prefix}{column}, {SCORE_DEFAULT})))"


def sql_final_score_expr(alias: str = "p", rounded: bool = True) -> str:
    tech, composition, color, emotion = [
        _sql_score_part(alias, column) for column in SCORE_PART_COLUMNS
    ]
    parts = [tech, composition, color, emotion]
    low = f"MIN({', '.join(parts)})"
    high = f"MAX({', '.join(parts)})"
    mean = f"(({tech}+{composition}+{color}+{emotion}) / 4.0)"
    spread = f"({high} - {low})"
    strong_count = " + ".join(
        f"(CASE WHEN {part} >= 7.0 THEN 1 ELSE 0 END)" for part in parts
    )
    weak_count = " + ".join(
        f"(CASE WHEN {part} <= 4.0 THEN 1 ELSE 0 END)" for part in parts
    )
    base = (
        f"(({tech}*{SCORE_PART_WEIGHTS[0]:.2f} + "
        f"{composition}*{SCORE_PART_WEIGHTS[1]:.2f} + "
        f"{color}*{SCORE_PART_WEIGHTS[2]:.2f} + "
        f"{emotion}*{SCORE_PART_WEIGHTS[3]:.2f}))"
    )
    weak_adjustment = f"(-0.10 * ({weak_count}))"
    short_adjustment = (
        f"(CASE WHEN {low} <= 2.5 THEN -0.35 "
        f"WHEN {low} <= 4.0 AND {high} >= 7.5 THEN -0.16 ELSE 0 END)"
    )
    spread_adjustment = (
        f"(CASE WHEN {spread} <= 1.0 AND {mean} >= 7.0 THEN 0.10 "
        f"WHEN {spread} >= 4.0 THEN (-0.16 - (({spread} - 4.0) * 0.03)) "
        f"WHEN {spread} >= 2.5 THEN -0.06 ELSE 0 END)"
    )
    strength_bonus = (
        f"(CASE WHEN {high} >= 8.0 AND ({strong_count}) >= 3 AND {low} >= 5.5 "
        f"THEN 0.08 ELSE 0 END)"
    )
    profile_adjustment = (
        f"(({composition} - {tech}) * 0.025 + "
        f"({emotion} - {color}) * 0.020 + "
        f"({high} + {low} - ({mean} * 2.0)) * 0.010)"
    )
    adjusted = (
        f"({base} + {weak_adjustment} + {short_adjustment} + "
        f"{spread_adjustment} + {strength_bonus} + {profile_adjustment})"
    )
    capped = (
        f"(CASE WHEN {low} <= 2.5 THEN MIN({adjusted}, 6.20) "
        f"WHEN {low} <= 4.0 THEN MIN({adjusted}, 7.60) "
        f"WHEN {low} <= 5.5 AND {high} >= 8.5 THEN MIN({adjusted}, 8.80) "
        f"ELSE {adjusted} END)"
    )
    expr = f"MIN(10.0, MAX(1.0, {capped}))"
    return f"ROUND(({expr} + 0.000000001), 2)" if rounded else expr


def sql_avg_score_expr(alias: str = "p") -> str:
    prefix = f"{alias}." if alias else ""
    score_expr = sql_final_score_expr(alias, rounded=False)
    return f"ROUND(AVG(CASE WHEN {prefix}id IS NULL THEN NULL ELSE {score_expr} END), 2)"


def avg_score(photo) -> float:
    scores = [
        photo["tech_score"],
        photo["composition_score"],
        photo["color_score"],
        photo["emotion_score"],
    ]
    return final_score_from_parts(scores)


def _load_index_font(size: int, bold: bool = False):
    names = (
        ("NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.otf", "wqy-microhei.ttc", "msyhbd.ttc", "simhei.ttf", "arialbd.ttf")
        if bold
        else ("NotoSansCJK-Regular.ttc", "NotoSansCJK-Regular.otf", "wqy-microhei.ttc", "msyh.ttc", "simsun.ttc", "arial.ttf")
    )
    font_dirs = [
        os.path.join(BASE_DIR, "assets", "fonts"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
        "/usr/share/fonts/opentype/noto",
        "/usr/share/fonts/truetype/noto",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/wqy",
    ]
    for font_dir in font_dirs:
        for name in names + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",):
            path = os.path.join(font_dir, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size=size)
                except Exception:
                    pass
    return ImageFont.load_default()


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    value = str(text or "")
    if draw.textlength(value, font=font) <= max_width:
        return value
    suffix = "..."
    while value and draw.textlength(value + suffix, font=font) > max_width:
        value = value[:-1]
    return value + suffix if value else suffix


def _text_height(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text or "Ag", font=font)
    return bbox[3] - bbox[1]


def _normalize_film_format(value: str | None) -> str:
    raw = str(value or "").lower()
    if "120" in raw:
        return "120"
    return "135"


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")


def _get_strip_format_dir(film_format: str) -> str:
    return os.path.join(FILM_STRIP_ASSET_DIR, _normalize_film_format(film_format))


def _get_template_root(film_format: str, template_name: str) -> str:
    return os.path.join(_get_strip_format_dir(film_format), _slugify(template_name))


def get_index_sheet_defaults(roll=None) -> dict:
    defaults = dict(INDEX_SHEET_DEFAULTS)
    if roll:
        defaults["film_info"] = roll["film_type"] or "FILM 135"
        templates = list_strip_templates(roll["film_format"])
        defaults["strip_template"] = templates[0]["value"] if templates else ""
    return defaults


def list_strip_templates(film_format: str | None) -> list[dict]:
    templates = []
    format_dir = _get_strip_format_dir(film_format)
    if not os.path.isdir(format_dir):
        return templates
    for name in sorted(os.listdir(format_dir)):
        abs_dir = os.path.join(format_dir, name)
        if not os.path.isdir(abs_dir):
            continue
        value = _slugify(name)
        if not value:
            continue
        label = name.replace("_", " ").replace("-", " ").strip()
        templates.append({"value": value, "label": label or name})
    return templates


def _parse_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_hex_color(value, default: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.lower()
    return default


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = _parse_hex_color(value, "#000000").lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def normalize_index_sheet_options(raw: dict | None, roll=None) -> dict:
    defaults = get_index_sheet_defaults(roll)
    raw = raw or {}
    available_templates = {item["value"] for item in list_strip_templates(roll["film_format"] if roll else None)}
    strip_template = str(raw.get("strip_template") or defaults["strip_template"]).strip().lower()
    if strip_template not in available_templates:
        strip_template = defaults["strip_template"]
    return {
        "show_header": _parse_bool(raw.get("show_header"), defaults["show_header"]),
        "show_header_text": _parse_bool(raw.get("show_header_text"), defaults["show_header_text"]),
        "header_height": INDEX_135_LAYOUT["header_h"],
        "header_bg_color": _parse_hex_color(raw.get("header_bg_color"), defaults["header_bg_color"]),
        "header_brand": str(raw.get("header_brand") or defaults["header_brand"]).strip()[:80],
        "header_title": str(raw.get("header_title") or defaults["header_title"]).strip()[:120],
        "header_note": str(raw.get("header_note") or defaults["header_note"]).strip()[:160],
        "film_info": str(raw.get("film_info") or defaults["film_info"]).strip()[:120],
        "strip_template": strip_template,
        "border_size": _parse_int(raw.get("border_size"), defaults["border_size"], 0, 160),
        "border_color": _parse_hex_color(raw.get("border_color"), defaults["border_color"]),
        "strip_gap": _parse_int(raw.get("strip_gap"), defaults["strip_gap"], 0, 120),
    }


def _crop_landscape_ratio(im: Image.Image, ratio: float = 1.5) -> Image.Image:
    if im.height > im.width:
        im = im.rotate(-90, expand=True)
    src_ratio = im.width / im.height if im.height else ratio
    if src_ratio > ratio:
        new_w = max(1, int(im.height * ratio))
        left = (im.width - new_w) // 2
        im = im.crop((left, 0, left + new_w, im.height))
    elif src_ratio < ratio:
        new_h = max(1, int(im.width / ratio))
        top = (im.height - new_h) // 2
        im = im.crop((0, top, im.width, top + new_h))
    return im


def _make_index_frame(photo, frame_w: int, frame_h: int) -> Image.Image:
    if not photo:
        return Image.new("RGB", (frame_w, frame_h), INDEX_135_LAYOUT["empty_frame_fill"])
    source_rel = photo["image_path"] or photo["thumb_path"]
    source_abs = os.path.join(STATIC_DIR, source_rel)
    try:
        with Image.open(source_abs) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = _crop_landscape_ratio(im, frame_w / frame_h)
            return im.resize((frame_w, frame_h), Image.Resampling.LANCZOS)
    except Exception:
        return Image.new("RGB", (frame_w, frame_h), INDEX_135_LAYOUT["empty_frame_fill"])


def _paste_rgba(base: Image.Image, overlay: Image.Image, xy: tuple[int, int]):
    if overlay.mode == "RGBA":
        base.paste(overlay, xy, overlay)
    else:
        base.paste(overlay, xy)


def _draw_135_sheet_header(sheet: Image.Image, roll, film_model: str):
    layout = INDEX_135_LAYOUT
    draw = ImageDraw.Draw(sheet)
    width = sheet.width
    header_h = layout["header_h"]
    draw.rectangle((0, 0, width, header_h), fill=layout["header_bg"])
    divider_y = layout["header_divider_y"]
    draw.line(
        (0, divider_y, width, divider_y),
        fill=layout["header_divider_fill"],
        width=layout["header_divider_w"],
    )

    brand_font = _load_index_font(layout["header_brand_font_size"], bold=True)
    title_font = _load_index_font(layout["header_title_font_size"], bold=True)
    meta_font = _load_index_font(layout["header_meta_font_size"])
    date_font = _load_index_font(layout["header_date_font_size"])
    draw.text(
        (layout["header_brand_x"], layout["header_brand_y"]),
        layout["header_brand_text"],
        fill=layout["header_title_fill"],
        font=brand_font,
    )

    right_w = layout["header_right_w"]
    right_x = max(layout["header_brand_x"], width - right_w - layout["header_right_x_offset"])
    title = _ellipsize(draw, roll["title"] or film_model or "135 INDEX", title_font, right_w)
    meta = f"{film_model or roll['film_type'] or 'FILM 135'}  ISO {roll['iso'] or '-'}  {roll['camera_model'] or '-'}"
    date = f"{roll['main_location'] or '-'}  {roll['start_date'] or '-'} - {roll['end_date'] or '-'}"
    draw.text((right_x, layout["header_title_y"]), title, fill=layout["header_title_fill"], font=title_font)
    draw.text((right_x, layout["header_meta_y"]), _ellipsize(draw, meta, meta_font, right_w), fill=layout["header_meta_fill"], font=meta_font)
    draw.text((right_x, layout["header_date_y"]), _ellipsize(draw, date, date_font, right_w), fill=layout["header_date_fill"], font=date_font)


def _resolve_strip_template_dir(roll, options: dict) -> str:
    film_format = roll["film_format"] if roll else "135"
    template_name = options.get("strip_template") or ""
    format_dir = _get_strip_format_dir(film_format)
    template_dir = ""
    if template_name and os.path.isdir(format_dir):
        for name in os.listdir(format_dir):
            candidate = os.path.join(format_dir, name)
            if os.path.isdir(candidate) and _slugify(name) == template_name:
                template_dir = candidate
                break
    if not template_dir:
        raise ValueError("未找到可用的底片条模板，请先在模板目录中添加素材。")
    return template_dir


def _segment_filename(strip_index: int, frames_per_strip: int) -> str:
    start = strip_index * frames_per_strip + 1
    end = start + frames_per_strip - 1
    return f"{start}-{end}.png"


def _resolve_segment_template_path(template_dir: str, strip_index: int, frames_per_strip: int) -> str:
    path = os.path.join(template_dir, _segment_filename(strip_index, frames_per_strip))
    if not os.path.exists(path):
        raise ValueError(f"底片条模板缺少文件：{os.path.basename(path)}")
    return path


def _resolve_shared_sprocket_path(film_format: str) -> str | None:
    base_dir = _get_strip_format_dir(film_format)
    for name in ("sprocket_strip.png", "sprocket.png"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            return path
    return None


def _draw_135_sheet_header_with_options(sheet: Image.Image, roll, options: dict):
    layout = INDEX_135_LAYOUT
    draw = ImageDraw.Draw(sheet)
    width = sheet.width
    header_h = INDEX_135_LAYOUT["header_h"]
    draw.rectangle((0, 0, width, header_h), fill=_hex_to_rgb(options["header_bg_color"]))

    brand_font = _load_index_font(layout["header_brand_font_size"], bold=True)
    note_font = _load_index_font(layout["header_note_font_size"])
    title_font = _load_index_font(layout["header_title_font_size"], bold=True)
    meta_font = _load_index_font(layout["header_meta_font_size"])
    date_font = _load_index_font(layout["header_date_font_size"])
    extra_font = _load_index_font(layout["header_extra_font_size"])

    left_w = max(720, width - layout["header_right_w"] - layout["header_right_x_offset"] - layout["header_brand_x"] * 2)
    left_lines = [
        (
            _ellipsize(draw, options["header_brand"] or layout["header_brand_text"], brand_font, left_w),
            brand_font,
            layout["header_title_fill"],
        )
    ]
    if options.get("header_note"):
        left_lines.append((
            _ellipsize(draw, options["header_note"], note_font, left_w),
            note_font,
            layout["header_meta_fill"],
        ))
    left_gap = layout["header_line_gap"]
    left_h = sum(_text_height(draw, text, font) for text, font, _fill in left_lines) + left_gap * (len(left_lines) - 1)
    left_y = max(0, (header_h - left_h) // 2)
    for text, font, fill in left_lines:
        draw.text((layout["header_brand_x"], left_y), text, fill=fill, font=font)
        left_y += _text_height(draw, text, font) + left_gap

    if options.get("show_header_text"):
        right_w = layout["header_right_w"]
        right_x = max(layout["header_brand_x"], width - right_w - layout["header_right_x_offset"])
        title = options["header_title"]
        meta = f"{options['film_info'] or roll['film_type'] or 'FILM 135'}  ISO {roll['iso'] or '-'}"
        date = f"{roll['main_location'] or '-'}  {roll['start_date'] or '-'} - {roll['end_date'] or '-'}"
        extra = f"{roll['camera_model'] or '-'}  {roll['lens_model'] or '-'}"
        right_lines = []
        if title:
            right_lines.append((_ellipsize(draw, title, title_font, right_w), title_font, layout["header_title_fill"]))
        right_lines.extend([
            (_ellipsize(draw, meta, meta_font, right_w), meta_font, layout["header_meta_fill"]),
            (_ellipsize(draw, date, date_font, right_w), date_font, layout["header_meta_fill"]),
            (_ellipsize(draw, extra, extra_font, right_w), extra_font, layout["header_meta_fill"]),
        ])
        right_gap = layout["header_line_gap"]
        right_h = sum(_text_height(draw, text, font) for text, font, _fill in right_lines) + right_gap * (len(right_lines) - 1)
        right_y = max(0, (header_h - right_h) // 2)
        for text, font, fill in right_lines:
            draw.text((right_x, right_y), text, fill=fill, font=font)
            right_y += _text_height(draw, text, font) + right_gap


def _make_135_strip(photos: list, strip_index: int, roll, film_model: str, options: dict) -> Image.Image:
    layout = INDEX_135_LAYOUT
    template_dir = _resolve_strip_template_dir(roll, options)
    template_path = _resolve_segment_template_path(template_dir, strip_index, layout["frames_per_strip"])
    with Image.open(template_path) as template:
        strip = template.convert("RGBA")

    for idx in range(layout["frames_per_strip"]):
        photo = photos[idx] if idx < len(photos) else None
        frame = _make_index_frame(photo, layout["photo_w"], layout["photo_h"]).convert("RGBA")
        x = layout["photo_x"] + idx * layout["photo_step_x"]
        strip.paste(frame, (x, layout["photo_y"]))

    sprocket_path = _resolve_shared_sprocket_path(roll["film_format"])
    if sprocket_path:
        with Image.open(sprocket_path) as sprocket:
            sprocket = sprocket.convert("RGBA")
            _paste_rgba(strip, sprocket, (layout["sprocket_x"], layout["sprocket_top_y"]))
            _paste_rgba(strip, sprocket, (layout["sprocket_x"], layout["sprocket_bottom_y"]))
    return strip.convert("RGB")


def _generate_index_sheet_legacy(roll_id: int, film_model: str | None = None) -> str:
    """Generate a 135 film negative index sheet from six-frame strips."""
    ensure_dirs()
    roll = query_one("SELECT * FROM film_rolls WHERE id = ?", (roll_id,))
    photos = query_all("SELECT * FROM photos WHERE roll_id = ? ORDER BY frame_number", (roll_id,))
    if not roll:
        raise ValueError("Roll not found")
    if not photos:
        raise ValueError("No photos in this roll")
    film_format = (roll["film_format"] or "").lower()
    if "120" in film_format:
        raise ValueError("暂不支持生成120格式索引图。")
    if _normalize_film_format(roll["film_format"]) == "135" and not _resolve_shared_sprocket_path(roll["film_format"]):
        raise ValueError("135齿孔模板缺失，请在 assets/film_strips/135 中添加 sprocket_strip.png。")

    layout = INDEX_135_LAYOUT
    per_strip = layout["frames_per_strip"]
    strip_count = (len(photos) + per_strip - 1) // per_strip
    strips = []
    for strip_index in range(strip_count):
        start = strip_index * per_strip
        legacy_options = normalize_index_sheet_options({"film_info": film_model}, roll)
        strips.append(_make_135_strip(photos[start:start + per_strip], strip_index, roll, film_model or "", legacy_options))

    width = strips[0].width + layout["sheet_margin_x"] * 2
    strips_h = sum(strip.height for strip in strips) + layout["sheet_strip_gap"] * (len(strips) - 1)
    height = layout["header_h"] + strips_h + layout["sheet_margin_bottom"]
    sheet = Image.new("RGB", (width, height), layout["sheet_bg"])
    _draw_135_sheet_header(sheet, roll, film_model or "")
    y = layout["header_h"]
    for strip in strips:
        sheet.paste(strip, (layout["sheet_margin_x"], y))
        y += strip.height + layout["sheet_strip_gap"]

    out_name = f"roll_{roll_id}_index_{uuid.uuid4().hex[:8]}.jpg"
    out_abs = os.path.join(INDEX_DIR, out_name)
    sheet.save(out_abs, "JPEG", quality=94, optimize=True, progressive=True)
    rel = relative_static_path(out_abs)
    old_sheets = query_all("SELECT file_path FROM index_sheets WHERE roll_id = ?", (roll_id,))
    for old in old_sheets:
        old_abs = os.path.join(STATIC_DIR, old["file_path"])
        if os.path.abspath(old_abs) != os.path.abspath(out_abs) and os.path.exists(old_abs):
            try:
                os.remove(old_abs)
            except OSError:
                pass
    execute("DELETE FROM index_sheets WHERE roll_id = ?", (roll_id,))
    execute("INSERT INTO index_sheets(roll_id, file_path) VALUES (?, ?)", (roll_id, rel))
    return rel


def generate_index_sheet(roll_id: int, film_model: str | None = None, options: dict | None = None) -> str:
    """Generate a 135 film negative index sheet from six-frame strips."""
    ensure_dirs()
    roll = query_one("SELECT * FROM film_rolls WHERE id = ?", (roll_id,))
    photos = query_all("SELECT * FROM photos WHERE roll_id = ? ORDER BY frame_number", (roll_id,))
    if not roll:
        raise ValueError("Roll not found")
    if not photos:
        raise ValueError("No photos in this roll")
    if len(photos) > INDEX_135_MAX_PHOTOS:
        raise ValueError(f"图片数量过多，最多支持 {INDEX_135_MAX_PHOTOS} 张照片生成索引图。")
    film_format = (roll["film_format"] or "").lower()
    if "120" in film_format:
        raise ValueError("暂不支持生成120格式索引图。")
    if _normalize_film_format(roll["film_format"]) == "135" and not _resolve_shared_sprocket_path(roll["film_format"]):
        raise ValueError("135齿孔模板缺失，请在 assets/film_strips/135 中添加 sprocket_strip.png。")

    layout = INDEX_135_LAYOUT
    raw_options = dict(options or {})
    if film_model and "film_info" not in raw_options:
        raw_options["film_info"] = film_model
    merged_options = normalize_index_sheet_options(raw_options, roll)
    per_strip = layout["frames_per_strip"]
    strip_count = (len(photos) + per_strip - 1) // per_strip
    strips = []
    for strip_index in range(strip_count):
        start = strip_index * per_strip
        strips.append(_make_135_strip(
            photos[start:start + per_strip],
            strip_index,
            roll,
            merged_options["film_info"],
            merged_options,
        ))

    border_size = merged_options["border_size"]
    content_w = strips[0].width + layout["sheet_margin_x"] * 2
    width = content_w + border_size * 2
    header_h = merged_options["header_height"] if merged_options["show_header"] else 0
    header_strip_gap = merged_options["strip_gap"] if header_h else 0
    top_border = 0 if header_h else border_size
    strips_h = sum(strip.height for strip in strips) + merged_options["strip_gap"] * (len(strips) - 1)
    height = top_border + header_h + header_strip_gap + strips_h + border_size
    sheet = Image.new("RGB", (width, height), _hex_to_rgb(merged_options["border_color"]))
    if merged_options["show_header"]:
        header = Image.new("RGB", (width, header_h), _hex_to_rgb(merged_options["header_bg_color"]))
        _draw_135_sheet_header_with_options(header, roll, merged_options)
        sheet.paste(header, (0, 0))

    y = top_border + header_h + header_strip_gap
    for strip in strips:
        sheet.paste(strip, (border_size + layout["sheet_margin_x"], y))
        y += strip.height + merged_options["strip_gap"]

    out_name = f"roll_{roll_id}_index_{uuid.uuid4().hex[:8]}.jpg"
    out_abs = os.path.join(INDEX_DIR, out_name)
    sheet.save(out_abs, "JPEG", quality=94, optimize=True, progressive=True)
    rel = relative_static_path(out_abs)
    old_sheets = query_all("SELECT file_path FROM index_sheets WHERE roll_id = ?", (roll_id,))
    for old in old_sheets:
        old_abs = os.path.join(STATIC_DIR, old["file_path"])
        if os.path.abspath(old_abs) != os.path.abspath(out_abs) and os.path.exists(old_abs):
            try:
                os.remove(old_abs)
            except OSError:
                pass
    execute("DELETE FROM index_sheets WHERE roll_id = ?", (roll_id,))
    generated_at = local_timestamp()
    execute("INSERT INTO index_sheets(roll_id, file_path, generated_at) VALUES (?, ?, ?)", (roll_id, rel, generated_at))
    return rel
