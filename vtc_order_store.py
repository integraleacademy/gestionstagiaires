"""Durable VTC orders on the same persistent disk as the existing exam registrations."""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from exam_retakes import Store as RetakeStore, now


class Store:
    lock = RetakeStore.lock

    def __init__(self, host):
        self.root = Path(host.PERSIST_DIR) / "vtc_public_orders"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = self.root / "orders.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, stage TEXT NOT NULL, due REAL NOT NULL,
                    created REAL NOT NULL, ip TEXT NOT NULL, email TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS practical_slots (
                    id TEXT PRIMARY KEY, day TEXT NOT NULL, capacity INTEGER NOT NULL, details TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS practical_seats (
                    order_id TEXT PRIMARY KEY, slot_id TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS orders_due ON orders(due);
                CREATE INDEX IF NOT EXISTS orders_time ON orders(created);
            """)

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def add(self, row, ip):
        stamp = time.time()
        fingerprint = hashlib.sha256(ip.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM orders WHERE id=?", (row["id"],)).fetchone():
                return
            ip_count, email_count = db.execute("SELECT SUM(ip=?),SUM(email=?) FROM orders WHERE created>?",
                                  (fingerprint,row["person"]["email"],stamp-1800)).fetchone()
            if (ip_count or 0) >= 60 or (email_count or 0) >= 5:
                raise ValueError("Plusieurs demandes viennent d’être reçues. Réessayez dans 30 minutes ou contactez le centre.")
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (row["id"],row["stage"],0,stamp,fingerprint,
                                                                     row["person"]["email"],json.dumps(row)))

    def save(self, row):
        row["updated_at"] = now()
        with self.connect() as db:
            db.execute("UPDATE orders SET stage=?,due=?,payload=? WHERE id=?",
                       (row["stage"], row.get("due",0), json.dumps(row), row["id"]))

    def get(self, oid):
        with self.connect() as db:
            value = db.execute("SELECT payload FROM orders WHERE id=?", (oid,)).fetchone()
        return json.loads(value[0]) if value else None

    def pending(self):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM orders WHERE due>=0 AND due<=? ORDER BY due,created LIMIT 20", (time.time(),))]

    def recent(self, page):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM orders ORDER BY created DESC LIMIT 51 OFFSET ?", (page*50,))]

    def document(self, oid, kind):
        if not re.fullmatch(r"[0-9a-f]{32}", oid) or kind not in {"convention","signed","invoice","vehicle","completion"}:
            raise ValueError("Document inconnu.")
        return self.root / f"{oid}-{kind}.pdf"

    def slots(self, earliest):
        with self.connect() as db:
            rows = db.execute("""SELECT s.id,s.details,s.capacity-count(p.order_id) AS free
                FROM practical_slots s LEFT JOIN practical_seats p ON p.slot_id=s.id
                WHERE s.day>=? AND s.active=1 GROUP BY s.id HAVING free>0 ORDER BY s.day,s.details""",
                (earliest,)).fetchall()
        return [dict(json.loads(details), id=key, free=free) for key,details,free in rows]

    def publish(self, key, slot, capacity):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO practical_slots(id,day,capacity,details) VALUES(?,?,?,?)",
                       (key,slot["day"],capacity,json.dumps(slot)))

    def close_slot(self, key):
        with self.connect() as db:
            db.execute("UPDATE practical_slots SET active=0 WHERE id=?", (key,))

    def claim(self, row, earliest):
        key = row.get("selected_slot")
        if not key:
            return None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute("SELECT details, capacity FROM practical_slots WHERE id=? AND day>=? AND active=1",
                                (key,earliest)).fetchone()
            if not record:
                return None
            # Recover the reservation if a process stopped between seat and order checkpoints.
            if not db.execute("SELECT 1 FROM practical_seats WHERE order_id=? AND slot_id=?",(row["id"],key)).fetchone():
                count = db.execute("SELECT COUNT(*) FROM practical_seats WHERE slot_id=?",(key,)).fetchone()[0]
                if count >= record[1]:
                    return None
                db.execute("INSERT INTO practical_seats VALUES(?,?)", (row["id"],key))
        return json.loads(record[0])
