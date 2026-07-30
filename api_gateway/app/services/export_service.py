"""CSV export shared by every table that has an Export button."""
import csv
import io


def to_csv(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return ""
    columns = columns or list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in columns})
    return buf.getvalue()
