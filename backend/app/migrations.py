"""Additive, transactional upgrades; never rewrite historical review payloads."""
def migrate(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version > 9:
        raise RuntimeError('数据库版本高于当前服务支持版本')
    if version < 6:
        statements = [
            '''CREATE TABLE IF NOT EXISTS material_versions(id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES contracts(id), idem TEXT NOT NULL, request_hash TEXT NOT NULL, content BLOB NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(contract_id,idem))''',
            '''CREATE TABLE IF NOT EXISTS material_bundles(id TEXT PRIMARY KEY, contract_id TEXT NOT NULL REFERENCES contracts(id), version_id TEXT NOT NULL REFERENCES versions(id), payload TEXT NOT NULL, created_at TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS active_material_bundles(contract_id TEXT PRIMARY KEY REFERENCES contracts(id), bundle_id TEXT NOT NULL REFERENCES material_bundles(id))''',
            '''CREATE TABLE IF NOT EXISTS supplement_requests(contract_id TEXT NOT NULL REFERENCES contracts(id), idem TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(contract_id,idem))''',
        ]
        for statement in statements:
            db.execute(statement)
        db.execute('PRAGMA user_version=6')

    if version < 7:
        for statement in [
            "CREATE TABLE IF NOT EXISTS editor_sessions(id TEXT PRIMARY KEY,contract_id TEXT NOT NULL REFERENCES contracts(id),client_id TEXT NOT NULL,idem TEXT NOT NULL,document_key TEXT UNIQUE NOT NULL,base_version_id TEXT NOT NULL,head_version_id TEXT NOT NULL,state TEXT NOT NULL,lease_until REAL NOT NULL,created_at TEXT NOT NULL,UNIQUE(contract_id,idem))",
            "CREATE UNIQUE INDEX IF NOT EXISTS editor_single_writer ON editor_sessions(contract_id) WHERE state IN ('open','closing')",
            "CREATE TABLE IF NOT EXISTS editor_save_requests(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES editor_sessions(id),idem TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(session_id,idem))",
            "CREATE TABLE IF NOT EXISTS editor_snapshot_candidates(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,sha256 TEXT NOT NULL,content BLOB NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(session_id,sha256))",
            "CREATE TABLE IF NOT EXISTS editor_callback_receipts(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,payload_hash TEXT NOT NULL,content_sha TEXT,status INTEGER NOT NULL,created_at TEXT NOT NULL)"
        ]: db.execute(statement)
        db.execute('PRAGMA user_version=7')

    if version < 8:
        for statement in [
            "CREATE TABLE IF NOT EXISTS legal_feedback(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),idem TEXT NOT NULL,request_hash TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(run_id,idem))",
            "CREATE TABLE IF NOT EXISTS legal_cases(id TEXT PRIMARY KEY,family_id TEXT NOT NULL,current_version_id TEXT)",
            "CREATE TABLE IF NOT EXISTS legal_case_versions(id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES legal_cases(id),version INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(case_id,version))",
            "CREATE TABLE IF NOT EXISTS legal_casebook_releases(sequence INTEGER PRIMARY KEY AUTOINCREMENT,version TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)"
        ]:
            db.execute(statement)
        db.execute('PRAGMA user_version=8')

    if version < 9:
        db.execute('CREATE TABLE IF NOT EXISTS review_execution_states(run_id TEXT PRIMARY KEY REFERENCES runs(id),payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS review_execution_events(run_id TEXT NOT NULL REFERENCES runs(id),seq INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(run_id,seq))')
        db.execute('PRAGMA user_version=9')
