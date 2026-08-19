"""Independent re-verification of Pass 20 finding: cloud_backup.backup_data()
copies WAL-mode SQLite DBs without checkpointing.

Uses the REAL cloud_backup.backup_data() function, pointed at temp dirs via
CLOUD_BACKUP_PATH override and an explicit data_dir arg. Does not touch the
real data/ directory.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

tmp = Path(tempfile.mkdtemp(prefix="wal_backup_verify_"))
data_dir = tmp / "data"
sync_dir = tmp / "sync"
data_dir.mkdir()
sync_dir.mkdir()

os.environ["CLOUD_BACKUP_PATH"] = str(sync_dir)

db_path = data_dir / "execution_log.db"
con = sqlite3.connect(str(db_path))
con.execute("PRAGMA journal_mode=WAL")
con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, note TEXT)")
con.commit()
con.execute("INSERT INTO orders (note) VALUES ('committed row')")
con.commit()

wal_path = data_dir / "execution_log.db-wal"
print("WAL file exists after insert+commit:", wal_path.exists(), "size:", wal_path.stat().st_size if wal_path.exists() else None)

# Verify the row IS visible via a fresh connection to the live db (i.e. really committed)
con2 = sqlite3.connect(str(db_path))
rows = con2.execute("SELECT * FROM orders").fetchall()
print("Rows visible via fresh live connection:", rows)
con2.close()

# Now call the real backup_data()
import cloud_backup

result = cloud_backup.backup_data(data_dir=data_dir)
print("backup_data() returned:", result)

backup_db = sync_dir / "KalshiBot" / "data"
# find today's dir
subdirs = list(backup_db.iterdir())
print("Backup subdirs:", subdirs)
backup_file = subdirs[0] / "execution_log.db"
print("Backup file exists:", backup_file.exists(), "size:", backup_file.stat().st_size if backup_file.exists() else None)

# Check whether wal/shm sidecar files were copied
copied_names = [p.name for p in subdirs[0].iterdir()]
print("Files copied into backup dir:", copied_names)

try:
    bcon = sqlite3.connect(str(backup_file))
    brows = bcon.execute("SELECT * FROM orders").fetchall()
    print("Rows visible in BACKUP copy:", brows)
except sqlite3.OperationalError as e:
    print("OperationalError reading backup copy:", e)

con.close()
shutil.rmtree(tmp, ignore_errors=True)
