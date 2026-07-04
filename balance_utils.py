async def ensure_transactions_table(db):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor_tag TEXT,
            target_tag TEXT,
            amount INTEGER NOT NULL,
            comment TEXT
        )
    """)


def user_transaction_tags(telegram_id, tg_tag):
    tags = [f"id:{telegram_id}"]
    if tg_tag:
        tags.insert(0, tg_tag)
    return tags


async def get_user_balance(db, telegram_id):
    await ensure_transactions_table(db)
    async with db.execute(
        "SELECT tg_tag FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ) as cursor:
        row = await cursor.fetchone()

    tg_tag = row[0] if row else None
    tags = user_transaction_tags(telegram_id, tg_tag)
    placeholders = ",".join("?" for _ in tags)
    async with db.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE target_tag IN ({placeholders})",
        tags,
    ) as cursor:
        balance = (await cursor.fetchone())[0] or 0
    return balance


async def get_user_balance_by_tag(db, tg_tag):
    await ensure_transactions_table(db)
    async with db.execute(
        "SELECT telegram_id FROM users WHERE tg_tag = ?",
        (tg_tag,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return await get_user_balance(db, row[0])


async def sync_user_balance(db, telegram_id):
    balance = await get_user_balance(db, telegram_id)
    await db.execute(
        "UPDATE users SET balance = ? WHERE telegram_id = ?",
        (balance, telegram_id),
    )
    return balance


async def get_top_balances(db, limit=5):
    await ensure_transactions_table(db)
    async with db.execute(
        """
        SELECT
            u.name,
            u.tg_tag,
            COALESCE(SUM(t.amount), 0) AS computed_balance
        FROM users u
        LEFT JOIN transactions t
            ON t.target_tag = u.tg_tag
            OR t.target_tag = ('id:' || u.telegram_id)
        GROUP BY u.telegram_id, u.name, u.tg_tag
        ORDER BY computed_balance DESC
        LIMIT ?
        """,
        (limit,),
    ) as cursor:
        return await cursor.fetchall()
