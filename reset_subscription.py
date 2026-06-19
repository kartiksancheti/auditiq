"""
AuditIQ - Monthly Subscription Reset Script
Standalone -- does not touch api.py/auth.py, no app restart needed.
Uses only Python standard library (no extra pip installs required).
"""
import os
import calendar
import psycopg2
import psycopg2.extras
from datetime import date
from dotenv import load_dotenv

load_dotenv()


def add_one_month(d):
    month = d.month + 1
    year = d.year
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5434)),
        database=os.getenv("DB_NAME", "auditiq"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "VPS@31"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def reset_due_subscriptions():
    today = date.today()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT email, calls_used, calls_limit,
               subscription_start_date, subscription_end_date
        FROM users
        WHERE subscription_end_date IS NOT NULL
          AND subscription_end_date <= %s
    """, (today,))
    due_users = cur.fetchall()

    if not due_users:
        print("[" + str(today) + "] No subscriptions due for reset.")
        cur.close()
        conn.close()
        return

    for u in due_users:
        new_start = u["subscription_end_date"]
        new_end = add_one_month(new_start)

        cur.execute("""
            UPDATE users
            SET calls_used = 0,
                subscription_start_date = %s,
                subscription_end_date = %s
            WHERE email = %s
        """, (new_start, new_end, u["email"]))

        print("Reset " + u["email"] + ": calls_used " + str(u["calls_used"]) +
              " -> 0 | new cycle " + str(new_start) + " to " + str(new_end))

    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    reset_due_subscriptions()
