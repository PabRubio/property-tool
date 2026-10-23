import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from .providers import now


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name): os.unlink(name)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def folder(self, record_id):
        if not re.fullmatch(r"[a-f0-9]{32}", record_id):
            raise ValueError("Invalid record ID")
        return self.root / record_id

    def load(self, record_id):
        with self.lock:
            path = self.folder(record_id) / "record.json"
            if not path.exists(): raise FileNotFoundError("Record not found")
            return json.loads(path.read_text(encoding="utf-8"))

    def save(self, record, event=None):
        with self.lock:
            record["updated_at"] = now()
            if event:
                record["audit"].append({"at": now(), "revision": record["revision"], "event": event})
            atomic_json(self.folder(record["id"]) / "record.json", record)

    def create(self, inputs, mode="manual", evidence=None):
        enquiry = inputs.get('enquiry', {})
        record = {"id": uuid.uuid4().hex, "created_at": now(), "updated_at": now(), "revision": 1,
                  "mode": mode, "status": "needs_follow_up" if enquiry.get('kind')=='area' else "draft", "inputs": inputs, "evidence": evidence or {},
                  "analysis": None, "narrative": None, "approval": None, "photos": [], "artifacts": {}, "audit": []}
        record['consent'] = {'recorded_at': now(), 'terms_accepted': enquiry.get('terms_accepted', False),
                             'terms_url': '/terms', 'privacy_url': '/privacy', 'wording_version': '2026-10-23',
                             'feedback_call': enquiry.get('feedback_call', False), 'testimonial_contact': enquiry.get('testimonial_contact', False)}
        self.save(record, "Brief created")
        return record

    def delete(self, record_id):
        with self.lock:
            shutil.rmtree(self.folder(record_id))

    def invalidate(self, record, reason):
        # Keep snapshots for audit; only current revision downloads are exposed.
        atomic_json(self.folder(record["id"]) / "history" / ("revision-%s.json" % record["revision"]), record)
        record["revision"] += 1
        record.update(analysis=None, narrative=None, approval=None, artifacts={}, status="needs_follow_up" if record['inputs'].get('enquiry',{}).get('kind')=='area' else "draft")
        record.pop("job", None)
        self.save(record, reason)

    def listing(self):
        results = []
        with self.lock:
            for path in self.root.glob("*/record.json"):
                try:
                    r = json.loads(path.read_text())
                    item = {k:r[k] for k in ("id", "updated_at", "status", "mode", "revision")}
                    item.update(address=r["inputs"]["property"]["address"], postcode=r["inputs"]["property"]["postcode"], investor=r["inputs"]["investor"]["name"])
                    if r['inputs'].get('enquiry',{}).get('kind')=='area':
                        item.update(address=r['inputs']['enquiry']['area'], postcode='Area enquiry')
                    results.append(item)
                except (ValueError, KeyError):
                    continue
        return sorted(results, key=lambda r:r["updated_at"], reverse=True)
