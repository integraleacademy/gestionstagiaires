"""Move imported course versions with their assets; cache immutable editions locally."""
from contextlib import nullcontext
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile

from campus import db

CHUNK = 1024 * 1024


def initialize():
    with db.pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campus.schema'))")
        conn.execute("""CREATE TABLE IF NOT EXISTS campus_directory.course_files (
            path TEXT PRIMARY KEY, size BIGINT NOT NULL, digest TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS campus_directory.course_chunks (
            path TEXT REFERENCES campus_directory.course_files(path) ON DELETE CASCADE,
            part INTEGER NOT NULL, body BYTEA NOT NULL, PRIMARY KEY(path,part))""")


def _publish_file(conn, path, key):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Fichier de cours non régulier.")
    with path.open("rb") as f:
        checksum = hashlib.file_digest(f, "sha256").hexdigest()
        size = path.stat().st_size
        row = conn.execute("SELECT digest FROM campus_directory.course_files WHERE path=%s", (key,)).fetchone()
        if row and row[0] == checksum:
            return
        if row and not key.endswith("/current.json"):
            raise ValueError("Une version de cours publiée a changé de contenu.")
        conn.execute("DELETE FROM campus_directory.course_files WHERE path=%s", (key,))
        conn.execute("INSERT INTO campus_directory.course_files VALUES (%s,%s,%s)", (key, size, checksum))
        f.seek(0)
        second = hashlib.sha256()
        for part, data in enumerate(iter(lambda: f.read(CHUNK), b"")):
            second.update(data)
            conn.execute("INSERT INTO campus_directory.course_chunks VALUES (%s,%s,%s)", (key, part, data))
        if second.hexdigest() != checksum:
            raise OSError("Le fichier du cours a changé pendant son transfert.")


def publish(root, course_id=None, *, connection=None):
    courses = (Path(root) / "courses").resolve()
    if not courses.is_dir():
        return
    selected = [courses / course_id] if course_id else sorted(courses.iterdir())
    with (nullcontext(connection) if connection is not None else db.pool().connection()) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campus.catalog'))")
        for folder in selected:
            if folder.is_symlink() or not folder.is_dir() or folder.name.startswith("."):
                continue
            pointer = folder / "current.json"
            if not pointer.is_file():
                continue
            for edition in sorted(folder.iterdir()):
                if not edition.is_dir() or edition.is_symlink() or edition.name.startswith("."):
                    continue
                manifest = edition / "course.json"
                if not manifest.is_file():
                    continue
                files = [manifest, *(edition / "assets").rglob("*")]
                for file in files:
                    if file.is_file():
                        if not file.resolve().is_relative_to(edition.resolve()):
                            raise ValueError("Média de cours hors dossier.")
                        _publish_file(conn, file, file.relative_to(courses).as_posix())
            _publish_file(conn, pointer, pointer.relative_to(courses).as_posix())


def materialize(root, key):
    """Only called after CourseCatalog has validated the course, version and asset path."""
    parts = PurePosixPath(key)
    if parts.is_absolute() or ".." in parts.parts:
        raise ValueError("Chemin de cours invalide.")
    base = (Path(root) / "courses").resolve()
    destination = (base / parts).resolve()
    if not destination.is_relative_to(base):
        raise ValueError("Chemin de cours invalide.")
    mutable = parts.name == "current.json"
    if destination.is_file() and not mutable:
        return
    with db.pool().connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        row = conn.execute("SELECT size,digest FROM campus_directory.course_files WHERE path=%s", (key,)).fetchone()
        if not row:
            return
        size, checksum = row
        if mutable and destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == checksum:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as f:
                name = f.name
                hashed = hashlib.sha256()
                with conn.cursor(name="campus_course_download") as cur:
                    cur.execute("SELECT body FROM campus_directory.course_chunks WHERE path=%s ORDER BY part", (key,))
                    for (data,) in cur:
                        f.write(data)
                        hashed.update(data)
                if f.tell() != size or hashed.hexdigest() != checksum:
                    raise IOError("Copie du cours incomplète.")
            os.replace(name, destination)
        finally:
            if name:
                Path(name).unlink(missing_ok=True)
