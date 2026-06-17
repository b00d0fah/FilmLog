from __future__ import annotations

import os
import re
import sqlite3
from io import BytesIO
import tempfile
import zipfile
from flask import Flask, after_this_request, flash, jsonify, redirect, render_template, request, url_for, abort, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from config import DEBUG, HOST, MAX_CONTENT_LENGTH, PORT, SECRET_KEY, DB_PATH
from db import init_db, execute, query_all, query_one
from utils import allowed_file, save_photo_file, get_tags_for_photo, set_photo_tags, avg_score, generate_index_sheet, get_index_sheet_defaults, list_strip_templates, normalize_score, final_score_from_parts, sql_avg_score_expr, sql_final_score_expr, SCORE_OPTIONS, INDEX_135_MAX_PHOTOS
from time_utils import local_timestamp
from qwen_service import (
    analyze_photo_with_qwen,
    generate_roll_summary_with_qwen,
    get_qwen_config,
    qwen_is_ready,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# 作品榜单参数。
# 大师作品：最终评分 >= 8.50（四项 1.0-10.0 半分制加权校准）
MASTERPIECE_SCORE_THRESHOLD = 8.50
WORK_DISPLAY_LIMIT = 50
FEATURED_DISPLAY_LIMIT = 10
MASTERPIECE_DISPLAY_LIMIT = 10
WORK_DISPLAY_LIMIT_OPTIONS = [10, 20, 50, 100, 200]
WORK_ALL_LIMIT_VALUE = "all"
ISO_OPTIONS = [6, 8, 10, 12, 16, 20, 25, 32, 40, 50, 64, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400]
RECENT_ROLL_LIMIT = 6
SQL_FINAL_SCORE = sql_final_score_expr("p")
SQL_AVG_SCORE = sql_avg_score_expr("p")

init_db()


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    flash("上传文件总大小超过限制。当前演示版限制为 600MB，可在 app.py 中调大 MAX_CONTENT_LENGTH。", "danger")
    return redirect(request.referrer or url_for("index"))


@app.template_filter("score")
def score_filter(photo):
    return avg_score(photo)


def get_roll_or_404(roll_id: int):
    roll = query_one("SELECT * FROM film_rolls WHERE id = ?", (roll_id,))
    if not roll:
        abort(404)
    return roll


def static_abs_path(rel_path: str) -> str:
    return os.path.join(BASE_DIR, "static", rel_path)


def _remove_index_sheet_file(file_path: str | None):
    if not file_path:
        return
    abs_path = static_abs_path(file_path)
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def _remove_static_file(rel_path: str | None):
    if not rel_path:
        return
    abs_path = static_abs_path(rel_path)
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def _remove_photo_files(photo):
    if not photo:
        return
    _remove_static_file(photo["image_path"])
    _remove_static_file(photo["thumb_path"])


def _resequence_roll_photos(roll_id: int, moved_photo_id: int, target_frame_number: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        rows = conn.execute(
            """
            SELECT id
            FROM photos
            WHERE roll_id = ?
            ORDER BY COALESCE(frame_number, 999999), created_at, id
            """,
            (roll_id,),
        ).fetchall()
        ordered_ids = [row["id"] for row in rows if row["id"] != moved_photo_id]
        if moved_photo_id not in {row["id"] for row in rows}:
            return
        insert_at = max(0, min(target_frame_number - 1, len(ordered_ids)))
        ordered_ids.insert(insert_at, moved_photo_id)
        for index, photo_id in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE photos SET frame_number = ? WHERE id = ?", (index, photo_id))
        conn.commit()


def current_index_sheets(roll_id: int) -> list:
    rows = query_all("SELECT * FROM index_sheets WHERE roll_id=? ORDER BY generated_at DESC, id DESC", (roll_id,))
    current = []
    for sheet in rows:
        file_path = sheet["file_path"]
        exists = bool(file_path and os.path.exists(static_abs_path(file_path)))
        if exists and not current:
            current.append(sheet)
        else:
            _remove_index_sheet_file(file_path)
            execute("DELETE FROM index_sheets WHERE id = ?", (sheet["id"],))
    return current


def compact_roll_text(roll, scan=None) -> str:
    parts = [
        f"标题：{roll['title']}",
        f"胶卷：{roll['film_type'] or '-'}",
        f"ISO：{roll['iso'] or '-'}",
        f"相机：{roll['camera_model'] or '-'}",
        f"镜头：{roll['lens_model'] or '-'}",
        f"画幅：{roll['film_format'] or '-'}",
        f"地点：{roll['main_location'] or '-'}",
        f"时间：{roll['start_date'] or '-'} 至 {roll['end_date'] or '-'}",
        f"备注：{roll['note'] or '-'}",
    ]
    if scan:
        parts.extend([
            f"冲扫店：{scan['lab_name'] or '-'}",
            f"工艺：{scan['process_type'] or '-'}",
            f"减/迫冲：{scan['push_pull'] or '-'}",
            f"扫描仪：{scan['scanner_model'] or '-'}",
            f"冲扫评价：{scan['comment'] or '-'}",
        ])
    return "；".join(parts)


def compact_photo_text(photo, tags=None) -> str:
    tags = tags or []
    return "；".join([
        f"序号：#{photo['frame_number'] or '-'}",
        f"地点：{photo['location'] or '-'}",
        f"时间：{photo['shooting_time'] or '-'}",
        f"光圈：{photo['aperture'] or '-'}",
        f"快门：{photo['shutter_speed'] or '-'}",
        f"曝光补偿：{photo['exposure_compensation'] or '-'}",
        f"最终评分：{avg_score(photo)}",
        f"标签：{', '.join(tags) if tags else '-'}",
        f"备注：{photo['note'] or '-'}",
    ])


def get_roll_form_options() -> dict:
    fields = {
        "film_types": "film_type",
        "cameras": "camera_model",
        "lenses": "lens_model",
        "formats": "film_format",
        "locations": "main_location",
    }
    options = {}
    for key, column in fields.items():
        rows = query_all(
            f"""
            SELECT DISTINCT {column} AS value
            FROM film_rolls
            WHERE {column} IS NOT NULL AND {column} != ''
            ORDER BY {column}
            LIMIT 80
            """
        )
        options[key] = [row["value"] for row in rows]
    return options


@app.route("/")
def index():
    view = request.args.get("view", "dashboard").strip() or "dashboard"
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip()
    status = request.args.get("status", "").strip()
    filter_target = request.args.get("filter_target", "photos").strip()
    if filter_target not in {"photos", "rolls"}:
        filter_target = "photos"
    if status == "待冲扫":
        filter_target = "rolls"
    has_filter = bool(q or tag or status)
    roll_filter_active = has_filter and filter_target == "rolls"
    photo_filter_active = has_filter and filter_target == "photos"
    recent_limit = RECENT_ROLL_LIMIT

    sql = """
        SELECT DISTINCT fr.*,
               (SELECT COUNT(*) FROM photos p_count WHERE p_count.roll_id = fr.id) AS photo_count
        FROM film_rolls fr
    """
    params = []
    where = []
    if roll_filter_active and tag:
        sql += " JOIN photos p ON p.roll_id = fr.id JOIN photo_tags pt ON pt.photo_id = p.id JOIN tags t ON t.id = pt.tag_id"
        where.append("t.name = ?")
        params.append(tag)
    if roll_filter_active and q:
        like = f"%{q}%"
        where.append(
            """
            (
                fr.title LIKE ? OR fr.film_type LIKE ? OR fr.camera_model LIKE ? OR fr.main_location LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM photos p_q
                    LEFT JOIN photo_tags pt_q ON pt_q.photo_id = p_q.id
                    LEFT JOIN tags t_q ON t_q.id = pt_q.tag_id
                    WHERE p_q.roll_id = fr.id
                      AND (p_q.location LIKE ? OR p_q.note LIKE ? OR p_q.original_filename LIKE ? OR t_q.name LIKE ?)
                )
            )
            """
        )
        params.extend([like, like, like, like, like, like, like, like])
    if roll_filter_active and status:
        where.append("fr.status = ?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY fr.start_date DESC, fr.created_at DESC"
    roll_rows = query_all(sql, tuple(params))
    rolls = []
    for row in roll_rows:
        item = dict(row)
        thumbs = query_all(
            """
            SELECT id, thumb_path FROM photos
            WHERE roll_id = ?
            ORDER BY frame_number
            LIMIT 5
            """,
            (row["id"],),
        )
        item["preview_thumbs"] = [dict(thumb) for thumb in thumbs]
        rolls.append(item)

    photo_sql = f"""
        SELECT DISTINCT p.*, fr.title AS roll_title,
               {SQL_FINAL_SCORE} AS avg_score
        FROM photos p
        JOIN film_rolls fr ON fr.id = p.roll_id
    """
    photo_params = []
    photo_where = []
    if photo_filter_active and tag:
        photo_sql += " JOIN photo_tags pt ON pt.photo_id = p.id JOIN tags t ON t.id = pt.tag_id"
        photo_where.append("t.name = ?")
        photo_params.append(tag)
    if photo_filter_active and q:
        like = f"%{q}%"
        photo_where.append(
            "(fr.title LIKE ? OR fr.film_type LIKE ? OR fr.camera_model LIKE ? OR fr.main_location LIKE ? "
            "OR p.location LIKE ? OR p.note LIKE ? OR p.original_filename LIKE ? "
            "OR EXISTS ("
            "SELECT 1 FROM photo_tags pt_q JOIN tags t_q ON t_q.id = pt_q.tag_id "
            "WHERE pt_q.photo_id = p.id AND t_q.name LIKE ?"
            "))"
        )
        photo_params.extend([like, like, like, like, like, like, like, like])
    if photo_filter_active and status:
        photo_where.append("fr.status = ?")
        photo_params.append(status)
    if photo_filter_active and photo_where:
        photo_sql += " WHERE " + " AND ".join(photo_where)
    else:
        photo_sql += " WHERE 1 = 0"
    photo_sql += " ORDER BY p.created_at DESC LIMIT 160"
    filtered_photo_rows = query_all(photo_sql, tuple(photo_params))
    filtered_photos = []
    for row in filtered_photo_rows:
        item = dict(row)
        item["tags"] = get_tags_for_photo(row["id"])
        filtered_photos.append(item)

    recent_rolls = query_all(
        f"""
        SELECT fr.*,
               COUNT(p.id) AS photo_count,
               MIN(p.thumb_path) AS cover_thumb,
               {SQL_AVG_SCORE} AS avg_score
        FROM film_rolls fr
        LEFT JOIN photos p ON p.roll_id = fr.id
        GROUP BY fr.id
        ORDER BY fr.start_date DESC, fr.created_at DESC
        LIMIT ?
        """,
        (recent_limit,),
    )
    top_film = query_one(
        f"""
        SELECT film_type, COUNT(*) AS roll_count
        FROM film_rolls
        WHERE film_type IS NOT NULL AND film_type != ''
        GROUP BY film_type
        ORDER BY roll_count DESC, film_type
        LIMIT 1
        """
    )
    featured_photo = query_one(
        f"""
        SELECT p.*, fr.title AS roll_title,
               {SQL_FINAL_SCORE} AS avg_score
        FROM photos p JOIN film_rolls fr ON fr.id = p.roll_id
        WHERE p.is_featured = 1
        ORDER BY RANDOM()
        LIMIT 1
        """
    )
    recent_photos = query_all(
        f"""
        SELECT p.*, fr.title AS roll_title,
               {SQL_FINAL_SCORE} AS avg_score
        FROM photos p JOIN film_rolls fr ON fr.id = p.roll_id
        ORDER BY p.created_at DESC
        LIMIT 8
        """
    )
    camera_top = query_one(
        """
        SELECT camera_model AS name, COUNT(*) AS roll_count
        FROM film_rolls
        WHERE camera_model IS NOT NULL AND camera_model != ''
        GROUP BY camera_model
        ORDER BY roll_count DESC, camera_model
        LIMIT 1
        """
    )
    latest_summary = query_one(
        """
        SELECT ars.*, fr.title AS roll_title
        FROM ai_roll_summaries ars
        JOIN film_rolls fr ON fr.id = ars.roll_id
        ORDER BY ars.generated_at DESC
        LIMIT 1
        """
    )
    latest_roll = query_one("SELECT * FROM film_rolls ORDER BY start_date DESC, created_at DESC LIMIT 1")
    summary = {
        "roll_count": query_one("SELECT COUNT(*) AS c FROM film_rolls")["c"],
        "photo_count": query_one("SELECT COUNT(*) AS c FROM photos")["c"],
        "featured_count": query_one("SELECT COUNT(*) AS c FROM photos WHERE is_featured = 1")["c"],
        "top_film": top_film["film_type"] if top_film else "暂无数据",
        "top_film_count": top_film["roll_count"] if top_film else 0,
        "best_photo_title": f"{featured_photo['roll_title']} #{featured_photo['frame_number']}" if featured_photo else "暂无作品",
        "best_photo_score": featured_photo["avg_score"] if featured_photo else "-",
        "best_photo_id": featured_photo["id"] if featured_photo else None,
        "best_photo_thumb": featured_photo["thumb_path"] if featured_photo else "",
        "best_photo_image": featured_photo["image_path"] if featured_photo else "",
        "best_photo_description": featured_photo["ai_description"] if featured_photo and featured_photo["ai_description"] else "这张精选作品还没有留下 AI 描述。",
        "best_photo_orientation": "portrait" if featured_photo and (featured_photo["height"] or 0) > (featured_photo["width"] or 0) else "landscape",
        "camera_top": camera_top["name"] if camera_top else "暂无数据",
        "camera_top_count": camera_top["roll_count"] if camera_top else 0,
        "latest_roll_title": latest_roll["title"] if latest_roll else "暂无胶卷",
        "latest_summary_title": latest_summary["roll_title"] if latest_summary else "暂无 AI 复盘",
        "latest_summary_at": latest_summary["generated_at"] if latest_summary else "",
    }
    tags = query_all(
        """
        SELECT t.name, COUNT(pt.photo_id) AS photo_count
        FROM tags t
        LEFT JOIN photo_tags pt ON pt.tag_id = t.id
        LEFT JOIN tag_blacklist tb ON tb.name = t.name
        WHERE tb.id IS NULL
        GROUP BY t.id
        ORDER BY t.name
        """
    )
    return render_template(
        "index.html",
        rolls=rolls,
        filtered_photos=filtered_photos,
        recent_rolls=recent_rolls,
        recent_photos=recent_photos,
        summary=summary,
        tags=tags,
        q=q,
        tag=tag,
        status=status,
        filter_target=filter_target,
        has_filter=has_filter,
        view=view,
    )


@app.route("/roll/new", methods=["GET", "POST"])
def roll_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("胶卷标题不能为空。", "danger")
            return redirect(url_for("roll_new"))
        status_value = request.form.get("status") or "拍摄中"
        if status_value == "已冲扫":
            status_value = "待冲扫"
        end_date_value = None if status_value == "拍摄中" else request.form.get("end_date")
        roll_id = execute(
            """
            INSERT INTO film_rolls(
                title, film_type, iso, camera_model, lens_model, film_format,
                status, start_date, end_date, main_location, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                request.form.get("film_type"),
                request.form.get("iso") or None,
                request.form.get("camera_model"),
                request.form.get("lens_model"),
                request.form.get("film_format"),
                status_value,
                request.form.get("start_date"),
                end_date_value,
                request.form.get("main_location"),
                request.form.get("note"),
            ),
        )
        flash("胶卷档案已创建。", "success")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    return render_template("roll_form.html", roll=None, options=get_roll_form_options(), iso_options=ISO_OPTIONS)


@app.route("/roll/<int:roll_id>/edit", methods=["GET", "POST"])
def roll_edit(roll_id):
    roll = get_roll_or_404(roll_id)
    if request.method == "POST":
        status_value = request.form.get("status") or "拍摄中"
        if status_value == "已冲扫":
            status_value = "待冲扫"
        end_date_value = None if status_value == "拍摄中" else request.form.get("end_date")
        execute(
            """
            UPDATE film_rolls SET
                title=?, film_type=?, iso=?, camera_model=?, lens_model=?, film_format=?,
                status=?, start_date=?, end_date=?, main_location=?, note=?
            WHERE id=?
            """,
            (
                request.form.get("title"),
                request.form.get("film_type"),
                request.form.get("iso") or None,
                request.form.get("camera_model"),
                request.form.get("lens_model"),
                request.form.get("film_format"),
                status_value,
                request.form.get("start_date"),
                end_date_value,
                request.form.get("main_location"),
                request.form.get("note"),
                roll_id,
            ),
        )
        flash("胶卷档案已更新。", "success")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    return render_template("roll_form.html", roll=roll, options=get_roll_form_options(), iso_options=ISO_OPTIONS)


@app.route("/roll/<int:roll_id>/delete", methods=["POST"])
def roll_delete(roll_id):
    get_roll_or_404(roll_id)
    execute("DELETE FROM film_rolls WHERE id = ?", (roll_id,))
    flash("胶卷档案已删除。", "success")
    return redirect(url_for("index", view="rolls"))


@app.route("/roll/<int:roll_id>")
def roll_detail(roll_id):
    roll = get_roll_or_404(roll_id)
    scan = query_one("SELECT * FROM develop_scans WHERE roll_id = ?", (roll_id,))
    photos = query_all("SELECT * FROM photos WHERE roll_id = ? ORDER BY frame_number", (roll_id,))
    photo_items = []
    for p in photos:
        item = dict(p)
        item["tags"] = get_tags_for_photo(p["id"])
        item["avg_score"] = avg_score(p)
        photo_items.append(item)
    index_sheets = current_index_sheets(roll_id)
    ai_summary = query_one("SELECT * FROM ai_roll_summaries WHERE roll_id=? ORDER BY generated_at DESC LIMIT 1", (roll_id,))
    imported = len(photos)
    roll_stats = {
        "photo_count": imported,
        "featured_count": sum(1 for p in photo_items if p["is_featured"]),
        "avg_score": round(sum(p["avg_score"] for p in photo_items) / imported, 2) if imported else 0,
    }
    return render_template(
        "roll_detail.html",
        roll=roll,
        scan=scan,
        photos=photo_items,
        index_sheets=index_sheets,
        ai_summary=ai_summary,
        qwen_ready=qwen_is_ready(),
        qwen_config=get_qwen_config(),
        roll_stats=roll_stats,
        index_defaults=get_index_sheet_defaults(roll),
        index_strip_templates=list_strip_templates(roll["film_format"]),
        index_max_photos=INDEX_135_MAX_PHOTOS,
    )


@app.route("/roll/<int:roll_id>/scan", methods=["GET", "POST"])
def scan_edit(roll_id):
    roll = get_roll_or_404(roll_id)
    scan = query_one("SELECT * FROM develop_scans WHERE roll_id = ?", (roll_id,))
    if request.method == "POST":
        values = (
            roll_id,
            request.form.get("lab_name"),
            request.form.get("process_type"),
            request.form.get("push_pull"),
            request.form.get("scanner_model"),
            request.form.get("file_format"),
            request.form.get("scan_date"),
            request.form.get("comment"),
        )
        execute(
            """
            INSERT INTO develop_scans(
                roll_id, lab_name, process_type, push_pull, scanner_model, file_format, scan_date, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(roll_id) DO UPDATE SET
                lab_name=excluded.lab_name,
                process_type=excluded.process_type,
                push_pull=excluded.push_pull,
                scanner_model=excluded.scanner_model,
                file_format=excluded.file_format,
                scan_date=excluded.scan_date,
                comment=excluded.comment
            """,
            values,
        )
        flash("冲扫信息已保存。", "success")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    return render_template("scan_form.html", roll=roll, scan=scan)


@app.route("/roll/<int:roll_id>/upload", methods=["POST"])
def upload_photos(roll_id):
    get_roll_or_404(roll_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    files = request.files.getlist("photos")
    if not files:
        if is_ajax:
            return jsonify({"ok": False, "message": "请选择需要导入的照片。"}), 400
        flash("请选择需要导入的照片。", "warning")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    last = query_one("SELECT COALESCE(MAX(frame_number), 0) AS m FROM photos WHERE roll_id=?", (roll_id,))["m"]
    saved = 0
    skipped = 0
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            skipped += 1
            continue
        last += 1
        save_photo_file(f, roll_id, last)
        saved += 1
    if is_ajax:
        return jsonify({
            "ok": bool(saved),
            "saved": saved,
            "skipped": skipped,
            "redirect": url_for("roll_detail", roll_id=roll_id),
        })
    if saved:
        flash(f"成功导入 {saved} 张照片，并已生成缩略图。", "success")
    if skipped:
        flash(f"有 {skipped} 个文件格式不支持，已跳过。", "warning")
    return redirect(url_for("roll_detail", roll_id=roll_id))


@app.route("/photo/<int:photo_id>/edit", methods=["GET", "POST"])
def photo_edit(photo_id):
    photo = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        abort(404)
    if request.method == "POST":
        is_featured = 1 if request.form.get("is_featured") == "on" else 0
        frame_number_raw = request.form.get("frame_number")
        try:
            frame_number = int(frame_number_raw) if frame_number_raw else None
        except ValueError:
            frame_number = None
        execute(
            """
            UPDATE photos SET
                frame_number=?, shooting_time=?, location=?, aperture=?, shutter_speed=?, exposure_compensation=?,
                tech_score=?, composition_score=?, color_score=?, emotion_score=?, is_featured=?, note=?
            WHERE id=?
            """,
            (
                frame_number,
                request.form.get("shooting_time"),
                request.form.get("location"),
                request.form.get("aperture"),
                request.form.get("shutter_speed"),
                request.form.get("exposure_compensation"),
                normalize_score(request.form.get("tech_score")),
                normalize_score(request.form.get("composition_score")),
                normalize_score(request.form.get("color_score")),
                normalize_score(request.form.get("emotion_score")),
                is_featured,
                request.form.get("note"),
                photo_id,
            ),
        )
        if frame_number and frame_number > 0:
            _resequence_roll_photos(photo["roll_id"], photo_id, frame_number)
        set_photo_tags(photo_id, request.form.get("tags", "").split(","), append=False)
        flash("照片信息已保存。", "success")
        return redirect(url_for("roll_detail", roll_id=photo["roll_id"]))
    tags = ", ".join(get_tags_for_photo(photo_id))
    return render_template("photo_edit.html", photo=photo, tags=tags, score_options=SCORE_OPTIONS, qwen_ready=qwen_is_ready(), qwen_config=get_qwen_config())


@app.route("/photo/<int:photo_id>/delete", methods=["POST"])
def photo_delete(photo_id):
    photo = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        abort(404)
    roll_id = photo["roll_id"]
    _remove_photo_files(photo)
    execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    flash("照片记录已删除。", "success")
    return redirect(url_for("roll_detail", roll_id=roll_id))


@app.route("/roll/<int:roll_id>/photos/delete", methods=["POST"])
def roll_delete_photos(roll_id):
    get_roll_or_404(roll_id)
    raw_ids = request.form.get("ids", "")
    ids = [int(item) for item in raw_ids.split(",") if item.strip().isdigit()]
    if not ids:
        flash("请先选择要删除的照片。", "warning")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    placeholders = ",".join("?" for _ in ids)
    photos = query_all(
        f"SELECT * FROM photos WHERE roll_id = ? AND id IN ({placeholders})",
        (roll_id, *ids),
    )
    matched_ids = [photo["id"] for photo in photos]
    if not matched_ids:
        flash("没有可删除的照片。", "warning")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    for photo in photos:
        _remove_photo_files(photo)
    matched_placeholders = ",".join("?" for _ in matched_ids)
    execute(f"DELETE FROM photos WHERE id IN ({matched_placeholders})", tuple(matched_ids))
    flash(f"已删除 {len(matched_ids)} 张照片，胶卷已保留。", "success")
    return redirect(url_for("roll_detail", roll_id=roll_id))


@app.route("/photo/<int:photo_id>/toggle_featured", methods=["POST"])
def photo_toggle_featured(photo_id):
    photo = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        abort(404)
    next_value = 0 if photo["is_featured"] else 1
    execute("UPDATE photos SET is_featured = ? WHERE id = ?", (next_value, photo_id))
    flash("精选状态已更新。", "success")
    return redirect(url_for("roll_detail", roll_id=photo["roll_id"]))


@app.route("/photo/<int:photo_id>/download")
def photo_download(photo_id):
    photo = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        abort(404)
    path = static_abs_path(photo["image_path"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=photo["original_filename"] or os.path.basename(path))


@app.route("/roll/<int:roll_id>/download_photos")
def roll_download_photos(roll_id):
    get_roll_or_404(roll_id)
    ids = []
    for raw in request.args.get("ids", "").split(","):
        raw = raw.strip()
        if raw.isdigit():
            ids.append(int(raw))
    if not ids:
        abort(400)
    placeholders = ",".join("?" for _ in ids)
    photos = query_all(
        f"SELECT * FROM photos WHERE roll_id = ? AND id IN ({placeholders}) ORDER BY frame_number",
        (roll_id, *ids),
    )
    if not photos:
        abort(404)
    if len(photos) == 1:
        photo = photos[0]
        path = static_abs_path(photo["image_path"])
        if not os.path.exists(path):
            abort(404)
        return send_file(path, as_attachment=True, download_name=photo["original_filename"] or os.path.basename(path))

    archive = tempfile.NamedTemporaryFile(prefix=f"roll_{roll_id}_", suffix=".zip", delete=False)
    archive_path = archive.name
    archive.close()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used_names = set()
        for photo in photos:
            path = static_abs_path(photo["image_path"])
            if not os.path.exists(path):
                continue
            name = photo["original_filename"] or os.path.basename(path)
            if name in used_names:
                root, ext = os.path.splitext(name)
                name = f"{root}_{photo['id']}{ext}"
            used_names.add(name)
            zf.write(path, name)

    @after_this_request
    def cleanup(response):
        try:
            os.remove(archive_path)
        except OSError:
            pass
        return response

    return send_file(archive_path, mimetype="application/zip", as_attachment=True, download_name=f"roll_{roll_id}_photos.zip")


@app.route("/roll/<int:roll_id>/index_sheet", methods=["POST"])
def index_sheet(roll_id):
    roll = get_roll_or_404(roll_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    try:
        if "120" in (roll["film_format"] or "").lower():
            raise ValueError("暂不支持生成120格式索引图。")
        options = {
            "show_header": request.form.get("show_header"),
            "show_header_text": request.form.get("show_header_text"),
            "header_bg_color": request.form.get("header_bg_color"),
            "header_brand": request.form.get("header_brand"),
            "header_title": request.form.get("header_title"),
            "header_note": request.form.get("header_note"),
            "film_info": request.form.get("film_info") or request.form.get("film_model"),
            "strip_template": request.form.get("strip_template"),
            "border_size": request.form.get("border_size"),
            "border_color": request.form.get("border_color"),
            "strip_gap": request.form.get("strip_gap"),
        }
        film_model = (options["film_info"] or roll["film_type"] or "FILM 135").strip()
        rel = generate_index_sheet(roll_id, film_model=film_model, options=options)
        if is_ajax:
            return jsonify({"ok": True, "file_path": rel, "url": url_for("static", filename=rel)})
        return redirect(url_for("roll_detail", roll_id=roll_id, focus="index"))
    except Exception as exc:
        if is_ajax:
            return jsonify({"ok": False, "message": str(exc)}), 500
        flash(str(exc), "danger")
    return redirect(url_for("roll_detail", roll_id=roll_id))


@app.route("/roll/<int:roll_id>/index_sheet/delete", methods=["POST"])
def index_sheet_delete(roll_id):
    get_roll_or_404(roll_id)
    sheets = query_all("SELECT * FROM index_sheets WHERE roll_id = ?", (roll_id,))
    for sheet in sheets:
        _remove_index_sheet_file(sheet["file_path"])
    execute("DELETE FROM index_sheets WHERE roll_id = ?", (roll_id,))
    flash("索引图已删除。", "success")
    return redirect(url_for("roll_detail", roll_id=roll_id, focus="index") + "#index-sheets")


def analyze_and_overwrite_photo(photo):
    roll = get_roll_or_404(photo["roll_id"])
    scan = query_one("SELECT * FROM develop_scans WHERE roll_id = ?", (roll["id"],))
    tags = get_tags_for_photo(photo["id"])
    result = analyze_photo_with_qwen(
        image_abs_path=static_abs_path(photo["image_path"]),
        roll_text=compact_roll_text(roll, scan),
        photo_text=compact_photo_text(photo, tags),
        fallback_tags=tags,
    )
    location_parts = {
        part.strip()
        for part in re.split(r"[/,，、\s]+", roll["main_location"] or "")
        if part.strip()
    }
    blocked_location_tags = location_parts | ({roll["main_location"].strip()} if roll["main_location"] else set())
    suggested_tags = [
        str(t).strip()
        for t in result.get("suggested_tags", [])
        if str(t).strip() and str(t).strip() not in blocked_location_tags
    ]
    scores = result.get("scores") or {}
    generated_at = local_timestamp()
    execute(
        """
        UPDATE photos SET
            ai_description=?,
            ai_suggested_tags=?,
            ai_reason=?,
            ai_score_reason=?,
            tech_score=?,
            composition_score=?,
            color_score=?,
            emotion_score=?,
            ai_generated_at=?
        WHERE id=?
        """,
        (
            str(result.get("description") or ""),
            ",".join(suggested_tags),
            str(result.get("reason") or ""),
            str(result.get("score_reason") or ""),
            normalize_score(scores.get("tech_score", photo["tech_score"])),
            normalize_score(scores.get("composition_score", photo["composition_score"])),
            normalize_score(scores.get("color_score", photo["color_score"])),
            normalize_score(scores.get("emotion_score", photo["emotion_score"])),
            generated_at,
            photo["id"],
        ),
    )
    set_photo_tags(photo["id"], suggested_tags, append=False)
    avg = final_score_from_parts(
        [
            scores.get("tech_score", photo["tech_score"]),
            scores.get("composition_score", photo["composition_score"]),
            scores.get("color_score", photo["color_score"]),
            scores.get("emotion_score", photo["emotion_score"]),
        ]
    )
    return {
        "tags": suggested_tags,
        "avg_score": avg,
        "description": str(result.get("description") or ""),
        "generated_at": generated_at,
    }


@app.route("/photo/<int:photo_id>/ai_analyze", methods=["POST"])
def photo_ai_analyze(photo_id):
    photo = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        abort(404)
    try:
        analyze_and_overwrite_photo(photo)
        flash("AI 已完成照片分析，并已覆盖旧分析、评分和标签。", "success")
    except Exception as exc:
        flash(f"AI 分析失败：{exc}", "danger")
    return redirect(url_for("photo_edit", photo_id=photo_id))


@app.route("/photo/<int:photo_id>/ai_analyze_json", methods=["POST"])
def photo_ai_analyze_json(photo_id):
    photo = query_one("SELECT * FROM photos WHERE id = ?", (photo_id,))
    if not photo:
        return jsonify({"ok": False, "message": "照片不存在。"}), 404
    if not qwen_is_ready():
        return jsonify({"ok": False, "message": "还没有配置千问 API。"}), 400
    try:
        result = analyze_and_overwrite_photo(photo)
        label = f"#{photo['frame_number'] or photo['id']}"
        score = result["avg_score"]
        tags = result["tags"][:6]
        tag_text = "、".join(tags) if tags else "无标签"
        return jsonify({
            "ok": True,
            "message": f"{label} 已分析 · 评分 {score} · {tag_text}",
            "photo_id": photo_id,
            "avg_score": score,
            "tags": tags,
            "generated_at": result["generated_at"],
        })
    except Exception as exc:
        label = f"#{photo['frame_number'] or photo['id']}"
        return jsonify({"ok": False, "message": f"{label} 分析失败：{exc}", "photo_id": photo_id}), 500


@app.route("/roll/<int:roll_id>/ai_analyze_photos", methods=["POST"])
def roll_ai_analyze_photos(roll_id):
    get_roll_or_404(roll_id)
    photos = query_all("SELECT * FROM photos WHERE roll_id = ? ORDER BY frame_number", (roll_id,))
    if not photos:
        flash("这卷胶片还没有导入照片，无法批量分析。", "warning")
        return redirect(url_for("roll_detail", roll_id=roll_id))
    if not qwen_is_ready():
        flash("还没有配置千问 API，无法批量分析照片。", "warning")
        return redirect(url_for("roll_detail", roll_id=roll_id))

    completed = 0
    failures = []
    for photo in photos:
        try:
            analyze_and_overwrite_photo(photo)
            completed += 1
        except Exception as exc:
            failures.append(f"#{photo['frame_number'] or photo['id']}: {exc}")

    if completed:
        flash(f"AI 已批量分析 {completed} 张照片，并覆盖旧分析、评分和标签。", "success")
    if failures:
        flash(f"有 {len(failures)} 张照片分析失败：" + "；".join(failures[:3]), "warning")
    return redirect(url_for("roll_detail", roll_id=roll_id))


@app.route("/roll/<int:roll_id>/ai_summary", methods=["POST"])
def roll_ai_summary(roll_id):
    roll = get_roll_or_404(roll_id)
    scan = query_one("SELECT * FROM develop_scans WHERE roll_id = ?", (roll_id,))
    photos = query_all("SELECT * FROM photos WHERE roll_id = ? ORDER BY frame_number", (roll_id,))
    if not photos:
        flash("这卷胶片还没有导入照片，无法生成 AI 复盘。", "warning")
        return redirect(url_for("roll_detail", roll_id=roll_id))

    all_tags = []
    rows = []
    scores = []
    featured = 0
    for p in photos:
        tags = get_tags_for_photo(p["id"])
        all_tags.extend(tags)
        score = avg_score(p)
        scores.append(score)
        featured += 1 if p["is_featured"] else 0
        rows.append(
            f"#{p['frame_number'] or '-'} | 评分{score} | 地点{p['location'] or '-'} | 标签{','.join(tags[:5]) or '-'} | 备注{p['note'] or '-'}"
        )
    avg = round(sum(scores) / len(scores), 2) if scores else 0
    tag_counts = {}
    for t in all_tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    stats_text = f"照片数量：{len(photos)}；精选数量：{featured}；平均评分：{avg}；高频标签：" + "、".join([f"{k}({v})" for k, v in top_tags])
    sample_text = "\n".join(rows[:30])

    try:
        summary = generate_roll_summary_with_qwen(
            roll_text=compact_roll_text(roll, scan),
            photo_table_text=sample_text,
            stats_text=stats_text,
        )
        generated_at = local_timestamp()
        execute("DELETE FROM ai_roll_summaries WHERE roll_id = ?", (roll_id,))
        execute(
            "INSERT INTO ai_roll_summaries(roll_id, summary, generated_at) VALUES (?, ?, ?)",
            (roll_id, summary, generated_at),
        )
        flash("AI 胶卷复盘已覆盖更新。", "success")
    except Exception as exc:
        flash(f"AI 复盘失败：{exc}", "danger")
    return redirect(url_for("roll_detail", roll_id=roll_id))


@app.route("/tag_blacklist/add", methods=["POST"])
def tag_blacklist_add():
    name = request.form.get("name", "").strip()
    if name:
        execute("INSERT OR IGNORE INTO tag_blacklist(name) VALUES (?)", (name,))
        flash(f"已将“{name}”加入标签黑名单。", "success")
    return redirect(request.referrer or url_for("stats"))


@app.route("/tag_blacklist")
def tag_blacklist():
    tag_candidates = query_all(
        """
        SELECT t.name, COUNT(pt.photo_id) AS photo_count
        FROM tags t
        JOIN photo_tags pt ON pt.tag_id = t.id
        LEFT JOIN tag_blacklist tb ON tb.name = t.name
        WHERE tb.id IS NULL
        GROUP BY t.id
        ORDER BY photo_count DESC, t.name
        LIMIT 200
        """
    )
    blacklisted_tags = query_all("SELECT * FROM tag_blacklist ORDER BY name")
    return render_template(
        "tag_blacklist.html",
        tag_candidates=tag_candidates,
        blacklisted_tags=blacklisted_tags,
    )


@app.route("/tag_blacklist/<int:item_id>/delete", methods=["POST"])
def tag_blacklist_delete(item_id):
    execute("DELETE FROM tag_blacklist WHERE id = ?", (item_id,))
    flash("已从标签黑名单移除。", "success")
    return redirect(request.referrer or url_for("stats"))


@app.route("/stats")
def stats():
    film_stats = query_all(
        f"""
        SELECT fr.film_type AS name, COUNT(p.id) AS photo_count,
               {SQL_AVG_SCORE} AS avg_score
        FROM film_rolls fr LEFT JOIN photos p ON p.roll_id = fr.id
        GROUP BY fr.film_type
        HAVING name IS NOT NULL AND name != ''
        ORDER BY avg_score DESC, photo_count DESC, name
        """
    )
    camera_stats = query_all(
        f"""
        SELECT fr.camera_model AS name,
               COUNT(DISTINCT fr.id) AS roll_count,
               {SQL_AVG_SCORE} AS avg_score
        FROM film_rolls fr
        LEFT JOIN photos p ON p.roll_id = fr.id
        WHERE fr.camera_model IS NOT NULL AND fr.camera_model != ''
        GROUP BY fr.camera_model
        ORDER BY avg_score DESC, roll_count DESC, name
        """
    )
    lab_stats = query_all(
        f"""
        SELECT ds.lab_name AS name, COUNT(DISTINCT fr.id) AS roll_count,
               {SQL_AVG_SCORE} AS avg_score
        FROM develop_scans ds
        JOIN film_rolls fr ON fr.id = ds.roll_id
        LEFT JOIN photos p ON p.roll_id = fr.id
        WHERE ds.lab_name IS NOT NULL AND ds.lab_name != ''
        GROUP BY ds.lab_name
        ORDER BY avg_score DESC, roll_count DESC, name
        """
    )
    photo_total = query_one("SELECT COUNT(*) AS c FROM photos")["c"]
    tag_stats = query_all(
        f"""
        SELECT t.name, COUNT(*) AS photo_count,
               {SQL_AVG_SCORE} AS avg_score
        FROM tags t JOIN photo_tags pt ON pt.tag_id = t.id
        JOIN photos p ON p.id = pt.photo_id
        LEFT JOIN tag_blacklist tb ON tb.name = t.name
        WHERE tb.id IS NULL
        GROUP BY t.id
        ORDER BY photo_count DESC, t.name
        LIMIT 30
        """
    )
    def selected_work_limit(name: str, *, default: int = WORK_DISPLAY_LIMIT, allow_all: bool = False):
        raw_value = request.args.get(name, str(default))
        if allow_all and raw_value == WORK_ALL_LIMIT_VALUE:
            return WORK_ALL_LIMIT_VALUE
        try:
            value = int(raw_value)
        except ValueError:
            value = default
        return value if value in WORK_DISPLAY_LIMIT_OPTIONS else default

    featured_limit = selected_work_limit("featured_limit", default=FEATURED_DISPLAY_LIMIT, allow_all=True)
    masterpiece_limit = selected_work_limit("masterpiece_limit", default=MASTERPIECE_DISPLAY_LIMIT, allow_all=True)
    annual_best_limit = selected_work_limit("best_limit")
    annual_years = [
        row["year"]
        for row in query_all(
            """
            SELECT DISTINCT substr(start_date, 1, 4) AS year
            FROM film_rolls
            WHERE start_date IS NOT NULL AND start_date != ''
            ORDER BY year DESC
            """
        )
        if row["year"]
    ]
    selected_year = request.args.get("year", "").strip()
    if selected_year and selected_year not in annual_years:
        selected_year = ""

    photo_score_sql = f"""
        SELECT p.*, fr.title AS roll_title, fr.start_date AS roll_start_date,
               {SQL_FINAL_SCORE} AS avg_score
        FROM photos p JOIN film_rolls fr ON fr.id = p.roll_id
    """
    annual_where_sql = "WHERE substr(roll_start_date, 1, 4) = ?" if selected_year else ""
    annual_params = (selected_year,) if selected_year else ()
    annual_title_year = selected_year or "全部年份"

    featured_limit_sql = "" if featured_limit == WORK_ALL_LIMIT_VALUE else "LIMIT ?"
    featured_params = () if featured_limit == WORK_ALL_LIMIT_VALUE else (featured_limit,)
    featured_photos = query_all(
        f"""
        SELECT * FROM ({photo_score_sql})
        WHERE is_featured = 1
        ORDER BY avg_score DESC, is_featured DESC, created_at DESC
        {featured_limit_sql}
        """,
        featured_params,
    )
    masterpiece_limit_sql = "" if masterpiece_limit == WORK_ALL_LIMIT_VALUE else "LIMIT ?"
    masterpiece_params = (MASTERPIECE_SCORE_THRESHOLD,) if masterpiece_limit == WORK_ALL_LIMIT_VALUE else (MASTERPIECE_SCORE_THRESHOLD, masterpiece_limit)
    masterpiece_photos = query_all(
        f"""
        SELECT * FROM ({photo_score_sql})
        WHERE avg_score >= ?
        ORDER BY avg_score DESC, is_featured DESC, created_at DESC
        {masterpiece_limit_sql}
        """,
        masterpiece_params,
    )
    masterpiece_count = query_one(
        f"""
        SELECT COUNT(*) AS c
        FROM ({photo_score_sql})
        WHERE avg_score >= ?
        """,
        (MASTERPIECE_SCORE_THRESHOLD,),
    )["c"]
    annual_best_photos = query_all(
        f"""
        SELECT * FROM ({photo_score_sql})
        {annual_where_sql}
        ORDER BY avg_score DESC, is_featured DESC, created_at DESC
        LIMIT ?
        """,
        annual_params + (annual_best_limit,),
    )

    return render_template(
        "stats.html",
        film_stats=film_stats,
        camera_stats=camera_stats,
        lab_stats=lab_stats,
        tag_stats=tag_stats,
        tag_stats_has_more=len(tag_stats) > 12,
        photo_total=photo_total,
        featured_photos=featured_photos,
        masterpiece_photos=masterpiece_photos,
        annual_best_photos=annual_best_photos,
        masterpiece_threshold=MASTERPIECE_SCORE_THRESHOLD,
        masterpiece_count=masterpiece_count,
        featured_limit=featured_limit,
        masterpiece_limit=masterpiece_limit,
        annual_best_limit=annual_best_limit,
        annual_years=annual_years,
        selected_year=selected_year,
        annual_title_year=annual_title_year,
        work_limit_options=WORK_DISPLAY_LIMIT_OPTIONS,
        work_all_limit_value=WORK_ALL_LIMIT_VALUE,
    )


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
