import datetime as dt
from typing import List, Optional, Sequence, Tuple

import aiosqlite


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        # Disable foreign keys for migration
        await db.execute("PRAGMA foreign_keys = OFF;")
        
        # Migration: drop old catalog tables and recreate promotions table
        old_promotions = None
        try:
            # Check if old promotions table exists with catalog_id
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='promotions'"
            )
            old_promotions_exists = await cursor.fetchone()
            
            if old_promotions_exists:
                # Check if it has catalog_id column
                cursor = await db.execute("PRAGMA table_info(promotions)")
                columns = await cursor.fetchall()
                has_catalog_id = any(col[1] == 'catalog_id' for col in columns)
                
                if has_catalog_id:
                    # Backup existing promotions data
                    cursor = await db.execute(
                        "SELECT id, title, description, link, image_file_id, created_at FROM promotions"
                    )
                    old_promotions = await cursor.fetchall()
                    
                    # Drop old tables
                    await db.execute("DROP TABLE IF EXISTS promotion_clicks;")
                    await db.execute("DROP TABLE IF EXISTS catalog_clicks;")
                    await db.execute("DROP TABLE IF EXISTS catalogs;")
                    await db.execute("DROP TABLE IF EXISTS promotions;")
                else:
                    # Just drop catalog tables
                    await db.execute("DROP TABLE IF EXISTS catalog_clicks;")
                    await db.execute("DROP TABLE IF EXISTS catalogs;")
            else:
                # Drop catalog tables if they exist
                await db.execute("DROP TABLE IF EXISTS catalog_clicks;")
                await db.execute("DROP TABLE IF EXISTS catalogs;")
        except Exception as e:
            print(f"Migration warning: {e}")
        
        # Create tables
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                claimed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                link TEXT NOT NULL,
                preview_image_file_id TEXT,
                image_file_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS promotion_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promotion_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
                user_id INTEGER,
                action TEXT NOT NULL,
                clicked_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users (tg_id);
            CREATE INDEX IF NOT EXISTS idx_promotion_clicks_promo ON promotion_clicks (promotion_id);
            CREATE INDEX IF NOT EXISTS idx_promotion_clicks_action ON promotion_clicks (action);
            """
        )
        
        # Restore old promotions data if we backed it up
        if old_promotions:
            try:
                for promo in old_promotions:
                    promo_id, title, description, link, image_file_id, created_at = promo
                    await db.execute(
                        """
                        INSERT INTO promotions (id, title, description, link, preview_image_file_id, image_file_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (promo_id, title, description, link, image_file_id, image_file_id, created_at)
                    )
            except Exception as e:
                print(f"Data restoration warning: {e}")
        
        # Add preview_image_file_id if it doesn't exist (for existing promotions table)
        try:
            await db.execute("ALTER TABLE promotions ADD COLUMN preview_image_file_id TEXT;")
        except Exception:
            pass
        
        # Ensure claimed column exists for older DBs
        try:
            await db.execute("ALTER TABLE users ADD COLUMN claimed INTEGER DEFAULT 0;")
        except Exception:
            pass
        
        # Re-enable foreign keys
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.commit()


async def register_user(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT OR IGNORE INTO users (tg_id, created_at, claimed) VALUES (?, ?, 0)
            """,
            (tg_id, _utcnow()),
        )
        await db.commit()


async def set_claimed(db_path: str, tg_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("UPDATE users SET claimed=1 WHERE tg_id=?", (tg_id,))
        await db.commit()


async def is_claimed(db_path: str, tg_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute("SELECT claimed FROM users WHERE tg_id=?", (tg_id,))
        row = await cursor.fetchone()
        return bool(row and row[0])


async def list_promotions(db_path: str) -> Sequence[Tuple]:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute(
            """
            SELECT id, title, description, link, preview_image_file_id, image_file_id
            FROM promotions
            ORDER BY created_at DESC
            """
        )
        return await cursor.fetchall()


async def get_promotion(db_path: str, promotion_id: int) -> Optional[Tuple]:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute(
            """
            SELECT id, title, description, link, preview_image_file_id, image_file_id
            FROM promotions WHERE id=?
            """,
            (promotion_id,),
        )
        return await cursor.fetchone()


async def add_promotion(
    db_path: str,
    title: str,
    description: str,
    link: str,
    preview_image_file_id: Optional[str],
    image_file_id: Optional[str],
) -> int:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute(
            """
            INSERT INTO promotions (title, description, link, preview_image_file_id, image_file_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, description, link, preview_image_file_id, image_file_id, _utcnow()),
        )
        await db.commit()
        return cursor.lastrowid


async def update_promotion_field(
    db_path: str, promotion_id: int, field: str, value: str
) -> None:
    allowed = {"title", "description", "link", "preview_image_file_id", "image_file_id"}
    if field not in allowed:
        raise ValueError(f"Invalid field: {field}")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(f"UPDATE promotions SET {field}=? WHERE id=?", (value, promotion_id))
        await db.commit()


async def delete_promotion(db_path: str, promotion_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("DELETE FROM promotions WHERE id=?", (promotion_id,))
        await db.commit()




async def log_promotion_click(
    db_path: str, promotion_id: int, action: str, user_id: Optional[int]
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT INTO promotion_clicks (promotion_id, action, user_id, clicked_at)
            VALUES (?, ?, ?, ?)
            """,
            (promotion_id, action, user_id, _utcnow()),
        )
        await db.commit()


async def top_promotions_all_time(db_path: str, limit: int = 10) -> List[Tuple]:
    """Get top promotions by redirect clicks (action='redirect')"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute(
            """
            SELECT p.id, COUNT(c.id) as cnt
            FROM promotions p
            LEFT JOIN promotion_clicks c ON c.promotion_id = p.id AND c.action = 'redirect'
            GROUP BY p.id
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (limit,),
        )
        return await cursor.fetchall()


async def stats(db_path: str) -> dict:
    start = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        # New users today
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= ?", (start.isoformat(),)
        )
        new_users = (await cursor.fetchone())[0]

        cursor = await db.execute(
            """
            SELECT promotions.title, COUNT(promotion_clicks.id) as cnt
            FROM promotions
            LEFT JOIN promotion_clicks ON promotion_clicks.promotion_id = promotions.id 
                AND promotion_clicks.action = 'redirect'
            GROUP BY promotions.id
            ORDER BY cnt DESC
            """
        )
        redirect_clicks = await cursor.fetchall()

        return {
            "new_users": new_users,
            "redirect_clicks": redirect_clicks,
        }

