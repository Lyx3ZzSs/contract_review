from contextlib import contextmanager
from pathlib import Path
import sqlite3
import json

SCHEMA = '''
CREATE TABLE IF NOT EXISTS contracts(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES contracts(id),
 revision INTEGER NOT NULL, sha256 TEXT NOT NULL, filename TEXT NOT NULL, content BLOB NOT NULL,
 parsed TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(contract_id,revision));
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES contracts(id),
 version_id TEXT NOT NULL REFERENCES versions(id), idem TEXT NOT NULL, request_hash TEXT NOT NULL,
 status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(contract_id,idem));
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 finding_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
 payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS extractions(id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 idem TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(version_id,idem));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,run_id TEXT UNIQUE REFERENCES runs(id),state TEXT NOT NULL,attempts INTEGER NOT NULL,owner TEXT,lease_until REAL);
CREATE TABLE IF NOT EXISTS draft_states(contract_id TEXT PRIMARY KEY REFERENCES contracts(id),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS party_previews(id TEXT PRIMARY KEY,payload TEXT NOT NULL,expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS import_requests(idem TEXT PRIMARY KEY,request_hash TEXT NOT NULL,payload TEXT NOT NULL);
'''


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            from .migrations import migrate
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            for cid in ('0932e3ea-fae0-4afc-8df0-ba254cd3a574', '8d5704b7-e441-46db-a590-9a6829acdb94'):
                row = db.execute('SELECT payload FROM contracts WHERE id=?', (cid,)).fetchone()
                if row:
                    value = json.loads(row['payload'])
                    if 'data_purpose' not in value:
                        value['data_purpose'] = 'test'
                        db.execute('UPDATE contracts SET payload=? WHERE id=?',
                                   (json.dumps(value, ensure_ascii=False), cid))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
