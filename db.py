import sqlite3
from contextlib import closing
from config import DB_PATH

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(cur, table: str, column: str) -> bool:
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _add_column_if_missing(cur, table: str, column: str, ddl: str):
    if not _column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS film_rolls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                film_type TEXT,
                iso INTEGER,
                camera_model TEXT,
                lens_model TEXT,
                film_format TEXT,
                expected_frames INTEGER DEFAULT 36,
                status TEXT DEFAULT '拍摄中',
                start_date TEXT,
                end_date TEXT,
                main_location TEXT,
                note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS develop_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_id INTEGER NOT NULL UNIQUE,
                lab_name TEXT,
                process_type TEXT,
                push_pull TEXT,
                scanner_model TEXT,
                file_format TEXT,
                scan_date TEXT,
                comment TEXT,
                FOREIGN KEY(roll_id) REFERENCES film_rolls(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_id INTEGER NOT NULL,
                frame_number INTEGER,
                original_filename TEXT,
                image_path TEXT NOT NULL,
                thumb_path TEXT NOT NULL,
                file_size_mb REAL,
                width INTEGER,
                height INTEGER,
                shooting_time TEXT,
                location TEXT,
                aperture TEXT,
                shutter_speed TEXT,
                exposure_compensation TEXT,
                tech_score REAL DEFAULT 5.5,
                composition_score REAL DEFAULT 5.5,
                color_score REAL DEFAULT 5.5,
                emotion_score REAL DEFAULT 5.5,
                is_featured INTEGER DEFAULT 0,
                note TEXT,
                auto_tags TEXT,
                ai_description TEXT,
                ai_suggested_tags TEXT,
                ai_reason TEXT,
                ai_score_reason TEXT,
                ai_generated_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(roll_id) REFERENCES film_rolls(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS tag_blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS photo_tags (
                photo_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY(photo_id, tag_id),
                FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS index_sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(roll_id) REFERENCES film_rolls(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ai_roll_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_id INTEGER NOT NULL,
                summary TEXT NOT NULL,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(roll_id) REFERENCES film_rolls(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_photos_roll_id ON photos(roll_id);
            CREATE INDEX IF NOT EXISTS idx_photos_roll_frame ON photos(roll_id, frame_number);
            CREATE INDEX IF NOT EXISTS idx_photo_tags_tag_id ON photo_tags(tag_id);
            CREATE INDEX IF NOT EXISTS idx_tag_blacklist_name ON tag_blacklist(name);
            CREATE INDEX IF NOT EXISTS idx_index_sheets_roll_id ON index_sheets(roll_id);
            CREATE INDEX IF NOT EXISTS idx_ai_roll_summaries_roll_id ON ai_roll_summaries(roll_id);
            """
        )
        for name in ("横构图", "竖构图", "方构图", "风景", "胶片", "胶片感", "胶片质感"):
            cur.execute("INSERT OR IGNORE INTO tag_blacklist(name) VALUES (?)", (name,))
        # 兼容已经运行过的旧版数据库：缺列则自动补列。
        _add_column_if_missing(cur, "photos", "ai_description", "ai_description TEXT")
        _add_column_if_missing(cur, "photos", "ai_suggested_tags", "ai_suggested_tags TEXT")
        _add_column_if_missing(cur, "photos", "ai_reason", "ai_reason TEXT")
        _add_column_if_missing(cur, "photos", "ai_score_reason", "ai_score_reason TEXT")
        _add_column_if_missing(cur, "photos", "ai_generated_at", "ai_generated_at TEXT")
        cur.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        score_migration = cur.execute("SELECT value FROM app_meta WHERE key = 'score_scale_v2'").fetchone()
        if not score_migration:
            for column in ("tech_score", "composition_score", "color_score", "emotion_score"):
                cur.execute(
                    f"""
                    UPDATE photos
                    SET {column} = CASE
                        WHEN {column} <= 1 THEN 1
                        WHEN {column} = 2 THEN 3
                        WHEN {column} = 3 THEN 4
                        WHEN {column} = 4 THEN 6
                        WHEN {column} = 5 THEN 7
                        ELSE MIN(7, MAX(1, {column}))
                    END
                    WHERE {column} IS NOT NULL
                    """
                )
            cur.execute("INSERT INTO app_meta(key, value) VALUES ('score_scale_v2', '1-7')")
        score_migration_v3 = cur.execute("SELECT value FROM app_meta WHERE key = 'score_scale_v3'").fetchone()
        if not score_migration_v3:
            for column in ("tech_score", "composition_score", "color_score", "emotion_score"):
                cur.execute(
                    f"""
                    UPDATE photos
                    SET {column} = ROUND(1.0 + ((MIN(7.0, MAX(1.0, {column})) - 1.0) * 1.5), 1)
                    WHERE {column} IS NOT NULL
                    """
                )
            cur.execute("INSERT INTO app_meta(key, value) VALUES ('score_scale_v3', '1-10-half-step')")
        cur.execute(
            """
            DELETE FROM ai_roll_summaries
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM ai_roll_summaries
                GROUP BY roll_id
            )
            """
        )
        conn.commit()


def query_all(sql, params=()):
    with closing(get_conn()) as conn:
        return conn.execute(sql, params).fetchall()


def query_one(sql, params=()):
    with closing(get_conn()) as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql, params=()):
    with closing(get_conn()) as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def executescript(sql):
    with closing(get_conn()) as conn:
        conn.executescript(sql)
        conn.commit()
