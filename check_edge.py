import sqlite3
from pathlib import Path

con = sqlite3.connect(str(Path("data/predictions.db")))
con.row_factory = sqlite3.Row

rows = con.execute("""
    SELECT city, condition_type, our_prob, market_prob, edge, predicted_at
    FROM predictions
    WHERE condition_type IN ('above', 'below')
    ORDER BY predicted_at DESC
    LIMIT 10
""").fetchall()

con.close()

print(
    f"{'city':12s} {'type':6s} {'our_p':6s} {'mkt_p':6s} {'edge':7s} {'predicted_at':16s}"
)
print("-" * 60)
for r in rows:
    print(
        f"{str(r['city'])[:12]:12s} {str(r['condition_type']):6s} "
        f"{r['our_prob']:.3f}  {r['market_prob']:.3f}  "
        f"{r['edge']:+.3f}  {str(r['predicted_at'])[:16]}"
    )
