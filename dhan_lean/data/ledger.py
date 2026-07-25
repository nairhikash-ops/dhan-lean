"""SQLite state ledger for source-neutral offline work items."""
import sqlite3, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dhan_lean.data.models import ClaimResult, ClaimStatus, DataWorkItem, RegistrationResult, RegistrationStatus, WorkItemAttempt

class StateLedger:
    def __init__(self, db_path: Path, storage_root: Path) -> None:
        self.db_path, self.storage_root = Path(db_path), Path(storage_root)
        if not self.storage_root.is_absolute(): raise ValueError("storage_root must be absolute")
        self._init()
    def _connect(self): return sqlite3.connect(self.db_path, isolation_level=None)
    def _init(self):
        c = self._connect()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS work_items (key TEXT PRIMARY KEY, source_id TEXT, symbol TEXT, day TEXT, start TEXT, end TEXT, output TEXT, state TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, key TEXT, n INTEGER, run_id TEXT, state TEXT, owner TEXT, claimed TEXT, lease INTEGER, expires TEXT, completed TEXT, error_code TEXT, error_summary TEXT)")
            columns = {row[1] for row in c.execute("PRAGMA table_info(work_items)")}
            if "bar_size" not in columns:
                c.execute("ALTER TABLE work_items ADD COLUMN bar_size TEXT NOT NULL DEFAULT '1m'")
        finally: c.close()
    def register_work_item(self, item: DataWorkItem) -> RegistrationResult:
        relative = item.output_directory.relative_to(self.storage_root).as_posix()
        c = self._connect()
        try:
            row = c.execute("SELECT source_id,symbol,bar_size,day,output FROM work_items WHERE key=?", (item.work_item_key,)).fetchone()
            values = (item.source_id, item.symbol, item.bar_size, item.session_date.isoformat(), relative)
            if row:
                if row != values: raise ValueError("work item key conflicts with existing metadata")
                return RegistrationResult(RegistrationStatus.EXISTING_MATCH, item.work_item_key, relative)
            c.execute("INSERT INTO work_items (key,source_id,symbol,bar_size,day,start,end,output,state) VALUES (?,?,?,?,?,?,?,?,?)", (item.work_item_key,item.source_id,item.symbol,item.bar_size,item.session_date.isoformat(),item.window.start.isoformat(),item.window.end.isoformat(),relative,"PLANNED"))
        finally: c.close()
        return RegistrationResult(RegistrationStatus.CREATED, item.work_item_key, relative)
    def get_work_item(self, key: str):
        c=self._connect()
        try: row=c.execute("SELECT source_id,symbol,bar_size,day,start,end,output FROM work_items WHERE key=?",(key,)).fetchone()
        finally: c.close()
        if not row: return None
        from datetime import date
        from dhan_lean.data.models import TimeWindow
        return DataWorkItem(row[1],row[0],row[2],date.fromisoformat(row[3]),TimeWindow(datetime.fromisoformat(row[4]),datetime.fromisoformat(row[5])),self.storage_root/row[6],key)
    def claim_work_item(self,key,claim_owner,lease_duration_seconds):
        now=datetime.now(timezone.utc); expires=now+timedelta(seconds=lease_duration_seconds)
        c=self._connect()
        try:
            c.execute("BEGIN IMMEDIATE"); row=c.execute("SELECT state FROM work_items WHERE key=?",(key,)).fetchone()
            if not row: c.execute("ROLLBACK"); return ClaimResult(ClaimStatus.WORK_ITEM_NOT_FOUND,key)
            status={"CLAIMED":ClaimStatus.ALREADY_CLAIMED,"SUCCEEDED":ClaimStatus.ALREADY_SUCCEEDED,"REVIEW_REQUIRED":ClaimStatus.REVIEW_REQUIRED}.get(row[0])
            if status: c.execute("ROLLBACK"); return ClaimResult(status,key)
            n=c.execute("SELECT count(*) FROM attempts WHERE key=?",(key,)).fetchone()[0]+1; aid=str(uuid.uuid4()); rid=now.strftime("%Y%m%dT%H%M%SZ")
            c.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(aid,key,n,rid,"CLAIMED",claim_owner,now.isoformat(),lease_duration_seconds,expires.isoformat(),None,None,None)); c.execute("UPDATE work_items SET state='CLAIMED' WHERE key=?",(key,)); c.execute("COMMIT")
        finally: c.close()
        return ClaimResult(ClaimStatus.CLAIMED,key,WorkItemAttempt(aid,key,n,rid,"CLAIMED",claim_owner,now.isoformat(),lease_duration_seconds,expires.isoformat()))
    def _complete(self, aid, state, work_state, code=None, summary=None):
        c=self._connect()
        try:
            row=c.execute("SELECT key,n,run_id,owner,claimed,lease,expires,state FROM attempts WHERE id=?",(aid,)).fetchone()
            if not row or row[7]!="CLAIMED": raise ValueError("attempt is not claimable")
            now=datetime.now(timezone.utc).isoformat(); c.execute("UPDATE attempts SET state=?,completed=?,error_code=?,error_summary=? WHERE id=?",(state,now,code,summary,aid)); c.execute("UPDATE work_items SET state=? WHERE key=?",(work_state,row[0]))
        finally: c.close()
        return WorkItemAttempt(aid,row[0],row[1],row[2],state,row[3],row[4],row[5],row[6],now,code,summary)
    def mark_attempt_succeeded(self, aid): return self._complete(aid,"SUCCEEDED","SUCCEEDED")
    def mark_attempt_failed(self, aid, error_code=None, error_summary=None): return self._complete(aid,"FAILED","REVIEW_REQUIRED",error_code,error_summary)
    def mark_attempt_interrupted(self, aid, error_code=None, error_summary=None): return self._complete(aid,"INTERRUPTED","REVIEW_REQUIRED",error_code,error_summary)
