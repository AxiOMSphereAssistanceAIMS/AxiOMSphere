# AIMS — Code Migrate (DB · Schema · Data · Backup · Rollback)

Migration target: **$ARGUMENTS**

_This skill runs on slot 120 (nemotron-3-super:120b) for safety-critical reasoning._

---

## Phase 0 — Parse and gate

From `$ARGUMENTS` determine:
- **target**: `db` (aims_registry.db) | `yaml` (config schema) | `jsonl` (data format) | `env`
- **op**: `add-column` | `add-table` | `rename` | `backfill` | `format-change` | `inspect`
- **scope**: table name or config section

**STOP conditions — must confirm with user before any write:**
- Any ALTER TABLE or DROP on `data/aims_registry.db`
- Any change to `ops/models/model_registry.yaml` slot bindings
- Any rename/delete of `aims_workspace/axi_ft_log/*.jsonl`

---

## Phase 1 — Backup (mandatory before any schema change)

```bash
cd /home/axi_omi_sphere/aims-workspace
TS=$(date +%Y%m%d_%H%M%S)

# DB backup
cp data/aims_registry.db "data/aims_registry.db.bak_${TS}" && \
  echo "Backup: data/aims_registry.db.bak_${TS}"

# Config backup (if yaml target)
cp ops/models/model_registry.yaml "ops/models/model_registry.yaml.bak_${TS}" 2>/dev/null && \
  echo "Backup: model_registry.yaml.bak_${TS}"

# Verify backup
ls -lh data/aims_registry.db* | head -5
```

---

## Phase 2 — Inspect current schema

```bash
# DB schema
python3 - <<'EOF'
import sqlite3
db = sqlite3.connect('data/aims_registry.db')
c = db.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
for t in tables:
    print(f"\n=== {t} ===")
    c.execute(f"PRAGMA table_info({t})")
    for col in c.fetchall():
        print(f"  {col[1]:30s} {col[2]:15s} nullable={not col[3]} default={col[4]}")
    c.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  Rows: {c.fetchone()[0]}")
db.close()
EOF
```

---

## Phase 3 — Apply migration

### 3a. Add column (safe — non-destructive)

```python
import sqlite3
db = sqlite3.connect('data/aims_registry.db')
# Only ALTER TABLE ADD COLUMN — never DROP, never RENAME without migration
db.execute("ALTER TABLE <table> ADD COLUMN <name> <type> DEFAULT <value>")
db.commit()
db.close()
```

### 3b. Add table (safe)

```python
import sqlite3
db = sqlite3.connect('data/aims_registry.db')
db.execute("""
CREATE TABLE IF NOT EXISTS <name> (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    <fields>
)
""")
db.commit()
db.close()
```

### 3c. Backfill existing rows

```python
import sqlite3
db = sqlite3.connect('data/aims_registry.db')
# Always use WHERE condition — never UPDATE without WHERE
db.execute("UPDATE <table> SET <col> = <value> WHERE <col> IS NULL")
affected = db.execute("SELECT changes()").fetchone()[0]
print(f"Backfilled {affected} rows")
db.commit()
db.close()
```

---

## Phase 4 — Verify migration

```bash
python3 - <<'EOF'
import sqlite3
db = sqlite3.connect('data/aims_registry.db')
c = db.cursor()

# Check new column/table exists
c.execute("PRAGMA table_info(<table>)")
cols = {r[1] for r in c.fetchall()}
assert "<new_column>" in cols, f"Column missing! Got: {cols}"

# Verify no data loss
c.execute("SELECT COUNT(*) FROM <table>")
print(f"Row count after migration: {c.fetchone()[0]}")

db.close()
print("Migration verified OK")
EOF
```

---

## Phase 5 — Rollback procedure

```bash
# Restore from backup (only if migration failed)
# cp data/aims_registry.db.bak_<TS> data/aims_registry.db
# echo "Rolled back to backup <TS>"

# Verify DB is accessible after rollback
python3 -c "import sqlite3; db = sqlite3.connect('data/aims_registry.db'); print('DB OK:', db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone())"
```

---

## Phase 6 — Output contract

```json
{
  "target": "$ARGUMENTS",
  "operation": "<add-column|add-table|backfill|inspect>",
  "backup_path": "data/aims_registry.db.bak_<timestamp>",
  "tables_affected": ["<table>"],
  "rows_affected": 0,
  "schema_before": {},
  "schema_after": {},
  "verified": true,
  "rollback_command": "cp <backup> data/aims_registry.db",
  "risk_level": "medium",
  "slot_used": "120"
}
```
