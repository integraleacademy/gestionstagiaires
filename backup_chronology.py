"""Order legacy manual and current automatic backups by snapshot time."""
import datetime
import re
from pathlib import Path


def backup_chronology_key(path):
    path = Path(path)
    match = re.search(r"(\d{8}T\d{6})(?:\.(\d{1,6}))?Z?", path.name)
    if match:
        try:
            stamp = datetime.datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
            stamp = stamp.replace(microsecond=int((match.group(2) or "0").ljust(6, "0")),
                                  tzinfo=datetime.timezone.utc)
            return stamp.timestamp(), path.name
        except ValueError:
            pass
    try:
        return path.stat().st_mtime, path.name
    except OSError:
        return 0, path.name
