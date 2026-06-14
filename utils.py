from __future__ import annotations

import os
import random
import uuid
from math import floor
from typing import Iterable, List
from PIL import Image, ImageDraw, ImageFont, ImageOps
from werkzeug.utils import secure_filename
from db import execute, query_all, query_one

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
THUMB_DIR = os.path.join(STATIC_DIR, "thumbs")
INDEX_DIR = os.path.join(STATIC_DIR, "index_sheets")
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


def _draw_contact_texture(draw: ImageDraw.ImageDraw, width: int, height: int, seed: int):
    rng = random.Random(seed)
    for _ in range(520):
        x = rng.randrange(0, width)
        y = rng.randrange(0, height)
        length = rng.randrange(10, 90)
        color = rng.choice(((18, 18, 18), (24, 23, 21), (9, 9, 9)))
        draw.line((x, y, min(width, x + length), y), fill=color, width=1)
    for _ in range(90):
        x = rng.randrange(0, width)
        y = rng.randrange(0, height)
        color = rng.choice(((36, 35, 32), (44, 41, 36), (12, 12, 12)))
        draw.point((x, y), fill=color)


def _draw_sprocket_row(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, top: bool):
    hole_w, hole_h, step = 26, 34, 56
    start = x + 14
    count = max(0, (width - 28) // step)
    for idx in range(count):
        hx = start + idx * step
        draw.rounded_rectangle(
            (hx, y, hx + hole_w, y + hole_h),
            radius=4,
            fill=(244, 244, 240),
            outline=(210, 210, 205),
        )


def _make_index_frame(photo, frame_w: int, frame_h: int) -> Image.Image:
    source_rel = photo["image_path"] or photo["thumb_path"]
    source_abs = os.path.join(STATIC_DIR, source_rel)
    try:
        with Image.open(source_abs) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            if im.height > im.width:
                im = im.rotate(-90, expand=True)
            im.thumbnail((frame_w, frame_h), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (frame_w, frame_h), (8, 8, 8))
            ox = (frame_w - im.width) // 2
            oy = (frame_h - im.height) // 2
            canvas.paste(im, (ox, oy))
            return canvas
    except Exception:
        return Image.new("RGB", (frame_w, frame_h), (28, 28, 28))


def generate_index_sheet(roll_id: int) -> str:
    """Generate a lab-style 35mm negative sleeve contact sheet."""
    ensure_dirs()
    roll = query_one("SELECT * FROM film_rolls WHERE id = ?", (roll_id,))
    photos = query_all("SELECT * FROM photos WHERE roll_id = ? ORDER BY frame_number", (roll_id,))
    if not roll:
        raise ValueError("Roll not found")
    if not photos:
        raise ValueError("No photos in this roll")

    cols = 6
    frame_w, frame_h = 460, 306
    frame_gap = 30
    strip_pad_x = 28
    page_margin_x = 34
    header_h = 244
    strip_gap = 44
    strip_h = frame_h + 140
    rows = (len(photos) + cols - 1) // cols
    strip_w = cols * frame_w + (cols - 1) * frame_gap + strip_pad_x * 2
    width = strip_w + page_margin_x * 2
    height = header_h + rows * strip_h + (rows - 1) * strip_gap + 58

    sheet = Image.new("RGB", (width, height), (250, 250, 246))
    draw = ImageDraw.Draw(sheet)

    font_brand = _load_index_font(72, bold=True)
    font_title = _load_index_font(40, bold=True)
    font_meta = _load_index_font(29)
    font_small = _load_index_font(23)

    draw.rectangle((0, 0, width, header_h), fill=(16, 16, 16))
    draw.line((0, header_h - 7, width, header_h - 7), fill=(236, 236, 232), width=5)
    draw.text((72, 54), "FilmLog", fill=(244, 244, 244), font=font_brand)

    title = _ellipsize(draw, roll["title"], font_title, width - 1080)
    meta_1 = f"{roll['film_type'] or 'Film'}  ISO {roll['iso'] or '-'}  {roll['camera_model'] or '-'}"
    meta_2 = f"{roll['main_location'] or '-'}  {roll['start_date'] or '-'} - {roll['end_date'] or '-'}"
    right_x = width - 760
    draw.text((right_x, 50), title, fill=(246, 246, 242), font=font_title)
    draw.text((right_x, 104), _ellipsize(draw, meta_1, font_meta, 700), fill=(190, 190, 182), font=font_meta)
    draw.text((right_x, 148), _ellipsize(draw, meta_2, font_small, 700), fill=(150, 150, 142), font=font_small)

    for idx, photo in enumerate(photos):
        row, col = divmod(idx, cols)
        strip_x = page_margin_x
        strip_y = header_h + row * (strip_h + strip_gap)
        if col == 0:
            draw.rounded_rectangle(
                (strip_x, strip_y, strip_x + strip_w, strip_y + strip_h),
                radius=4,
                fill=(1, 1, 1),
                outline=(28, 28, 26),
                width=2,
            )
            _draw_sprocket_row(draw, strip_x, strip_y + 15, strip_w, top=True)
            _draw_sprocket_row(draw, strip_x, strip_y + strip_h - 49, strip_w, top=False)

        frame_x = strip_x + strip_pad_x + col * (frame_w + frame_gap)
        frame_y = strip_y + 70
        frame = _make_index_frame(photo, frame_w, frame_h)
        sheet.paste(frame, (frame_x, frame_y))
        draw.rectangle((frame_x - 3, frame_y - 3, frame_x + frame_w + 2, frame_y + frame_h + 2), outline=(7, 7, 7), width=3)
        draw.rectangle((frame_x, frame_y, frame_x + frame_w - 1, frame_y + frame_h - 1), outline=(44, 44, 40), width=1)

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
