# core/rule_engine.py
# ─────────────────────────────────────────────
# Manages strategy rules dynamically.
# Rules can be ADDED, MODIFIED, WEAKENED, RETIRED
# by the AI evolution engine.
# ─────────────────────────────────────────────

import sqlite3
import json
from datetime import datetime
from loguru import logger
import config


class RuleEngine:

    def __init__(self, db_path: str = config.RULES_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name        TEXT UNIQUE,
                rule_type        TEXT,       -- ENTRY / EXIT / FILTER
                direction        TEXT,       -- LONG / SHORT / BOTH
                conditions       TEXT,       -- JSON list
                parameters       TEXT,       -- JSON dict of tunable params
                weight           REAL DEFAULT 1.0,
                status           TEXT DEFAULT 'ACTIVE',
                origin           TEXT DEFAULT 'MANUAL',
                created_at       TEXT,
                last_updated     TEXT,

                -- Performance
                total_signals    INTEGER DEFAULT 0,
                wins             INTEGER DEFAULT 0,
                losses           INTEGER DEFAULT 0,
                total_pnl        REAL DEFAULT 0.0,
                win_streak       INTEGER DEFAULT 0,
                loss_streak      INTEGER DEFAULT 0,
                last_result      TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rule_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name    TEXT,
                changed_at   TEXT,
                change_type  TEXT,   -- ADDED / MODIFIED / WEAKENED / RETIRED
                old_state    TEXT,   -- JSON
                new_state    TEXT,   -- JSON
                reason       TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────
    # ADD
    # ─────────────────────────────────────────
    def add_rule(self, rule: dict, origin: str = "MANUAL") -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT OR IGNORE INTO rules
                (rule_name, rule_type, direction, conditions, parameters,
                 weight, status, origin, created_at, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                rule['name'],
                rule.get('type', 'ENTRY'),
                rule.get('direction', 'LONG'),
                json.dumps(rule.get('conditions', [])),
                json.dumps(rule.get('parameters', {})),
                rule.get('weight', 1.0),
                'ACTIVE',
                origin,
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
            conn.close()
            self._log_change(rule['name'], 'ADDED', {}, rule,
                             rule.get('reasoning', 'Manually added'))
            logger.info(f"Rule added: {rule['name']} [{origin}]")
            return True
        except Exception as e:
            logger.error(f"Add rule error: {e}")
            return False

    # ─────────────────────────────────────────
    # UPDATE PERFORMANCE
    # ─────────────────────────────────────────
    def update_performance(self, rule_name: str, win: bool, pnl: float):
        """Called after every trade to track rule performance"""
        conn = sqlite3.connect(self.db_path)
        row  = conn.execute(
            "SELECT wins, losses, win_streak, loss_streak FROM rules WHERE rule_name=?",
            (rule_name,)
        ).fetchone()

        if not row:
            conn.close()
            return

        wins, losses, ws, ls = row
        if win:
            wins += 1; ws += 1; ls = 0
        else:
            losses += 1; ls += 1; ws = 0

        conn.execute("""
            UPDATE rules SET
                total_signals = total_signals + 1,
                wins     = ?,
                losses   = ?,
                total_pnl = total_pnl + ?,
                win_streak  = ?,
                loss_streak = ?,
                last_result = ?,
                last_updated = ?
            WHERE rule_name = ?
        """, (
            wins, losses, pnl,
            ws, ls,
            'WIN' if win else 'LOSS',
            datetime.now().isoformat(),
            rule_name
        ))
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────
    # MODIFY
    # ─────────────────────────────────────────
    def modify_rule(self, rule_name: str, updates: dict, reason: str):
        old = self.get_rule(rule_name)
        conn = sqlite3.connect(self.db_path)
        sets = []
        vals = []
        for k, v in updates.items():
            if k in ('conditions', 'parameters'):
                v = json.dumps(v)
            sets.append(f"{k}=?")
            vals.append(v)
        sets.append("last_updated=?")
        vals.append(datetime.now().isoformat())
        vals.append(rule_name)
        conn.execute(
            f"UPDATE rules SET {', '.join(sets)} WHERE rule_name=?", vals
        )
        conn.commit()
        conn.close()
        new = self.get_rule(rule_name)
        self._log_change(rule_name, 'MODIFIED', old, new, reason)
        logger.info(f"Rule modified: {rule_name} | {reason}")

    def weaken_rule(self, rule_name: str, new_weight: float, reason: str):
        old = self.get_rule(rule_name)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE rules SET weight=?, status='WEAKENED', last_updated=?
            WHERE rule_name=?
        """, (new_weight, datetime.now().isoformat(), rule_name))
        conn.commit()
        conn.close()
        new = self.get_rule(rule_name)
        self._log_change(rule_name, 'WEAKENED', old, new, reason)
        logger.warning(f"Rule weakened: {rule_name} → weight={new_weight} | {reason}")

    def retire_rule(self, rule_name: str, reason: str):
        old = self.get_rule(rule_name)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE rules SET status='RETIRED', last_updated=?
            WHERE rule_name=?
        """, (datetime.now().isoformat(), rule_name))
        conn.commit()
        conn.close()
        self._log_change(rule_name, 'RETIRED', old, {}, reason)
        logger.warning(f"Rule retired: {rule_name} | {reason}")

    def reactivate_rule(self, rule_name: str, reason: str = ""):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE rules SET status='ACTIVE', weight=1.0, last_updated=?
            WHERE rule_name=?
        """, (datetime.now().isoformat(), rule_name))
        conn.commit()
        conn.close()
        logger.info(f"Rule reactivated: {rule_name}")

    # ─────────────────────────────────────────
    # QUERIES
    # ─────────────────────────────────────────
    def get_active_rules(self) -> list:
        conn  = sqlite3.connect(self.db_path)
        rows  = conn.execute("""
            SELECT rule_name, rule_type, direction, conditions,
                   parameters, weight, origin,
                   total_signals, wins, losses, total_pnl
            FROM rules
            WHERE status IN ('ACTIVE','WEAKENED')
            ORDER BY weight DESC
        """).fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "name":          r[0],
                "type":          r[1],
                "direction":     r[2],
                "conditions":    json.loads(r[3]) if r[3] else [],
                "parameters":    json.loads(r[4]) if r[4] else {},
                "weight":        r[5],
                "origin":        r[6],
                "total_signals": r[7],
                "wins":          r[8],
                "losses":        r[9],
                "win_rate":      round(r[8] / max(r[7], 1) * 100, 1),
                "total_pnl":     r[10]
            })
        return result

    def get_rule(self, rule_name: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row  = conn.execute(
            "SELECT * FROM rules WHERE rule_name=?", (rule_name,)
        ).fetchone()
        conn.close()
        if row:
            cols = [d[0] for d in conn.description] if conn.description else []
            return dict(zip(cols, row))
        return {}

    def get_evolution_history(self, limit: int = 50) -> list:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT rule_name, changed_at, change_type, reason
            FROM rule_history
            ORDER BY changed_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [
            {"rule": r[0], "at": r[1], "change": r[2], "reason": r[3]}
            for r in rows
        ]

    def get_performance_summary(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT rule_name, total_signals, wins, losses, total_pnl, weight, status
            FROM rules ORDER BY total_pnl DESC
        """).fetchall()
        conn.close()
        return [
            {
                "name":      r[0],
                "signals":   r[1],
                "wins":      r[2],
                "losses":    r[3],
                "win_rate":  round(r[2] / max(r[1], 1) * 100, 1),
                "pnl":       r[4],
                "weight":    r[5],
                "status":    r[6]
            }
            for r in rows
        ]

    # ─────────────────────────────────────────
    # AUDIT TRAIL
    # ─────────────────────────────────────────
    def _log_change(self, rule_name: str, change_type: str,
                    old: dict, new: dict, reason: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO rule_history
            (rule_name, changed_at, change_type, old_state, new_state, reason)
            VALUES (?,?,?,?,?,?)
        """, (
            rule_name,
            datetime.now().isoformat(),
            change_type,
            json.dumps(old),
            json.dumps(new),
            reason
        ))
        conn.commit()
        conn.close()
