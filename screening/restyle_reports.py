"""Refresh saved presentation without re-running research or financial analysis.

Run: python3 -m screening.restyle_reports --root data/records
"""
import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import tempfile

from .editor import ReportEditor
from .providers import now
from .report_layout import render_report
from .store import Store, atomic_json


def restyle_report(store, record_id):
    """Publish one new main PDF and retain a complete pre-refresh snapshot."""
    with store.lock:
        folder=store.folder(record_id)
        record_path=folder/'record.json'
        original_bytes=record_path.read_bytes()
        original=json.loads(original_bytes)
        artifacts=original.get('artifacts') or {}
        if not artifacts.get('pdf'):
            return False
        if (artifacts.get('layout_version')==5 and artifacts.get('report_style')=='signature'
                and (folder/artifacts['pdf']).is_file()):
            return False
        if (original.get('job') or {}).get('state') in ('queued','running'):
            raise ValueError('Wait for the current report job before restyling '+record_id)
        if (original.get('analysis') or {}).get('version')!=5 or not original.get('narrative'):
            raise ValueError('Saved analysis is incompatible; restyling cannot recalculate '+record_id)
        as_of=artifacts.get('generated_at')
        if not as_of:
            raise ValueError('The saved report has no assessment timestamp: '+record_id)
        revised=copy.deepcopy(original)
        token=secrets.token_hex(6)
        name='r%s-%s-signature-%s.pdf'%(original['revision'],'reviewed' if artifacts.get('final') else 'draft',token)
        with tempfile.TemporaryDirectory(prefix='.restyle-',dir=str(folder)) as temporary:
            path=Path(temporary)/name
            editor=ReportEditor(revised)
            layout=render_report(revised,path,folder,editor,bool(artifacts.get('final')),as_of=as_of)
            revised['report_document']=editor.catalog
            # Numbering and source-register files remain valid after a restyle.
            if revised.get('report_citations')!=original.get('report_citations'):
                raise ValueError('Restyling would change the saved source register: '+record_id)
            revised['artifacts']=dict(artifacts,**layout,pdf=name,styled_at=now())
            if record_path.read_bytes()!=original_bytes:
                raise ValueError('The record changed during rendering; previous report kept: '+record_id)
            atomic_json(folder/'history'/('before-signature-'+token+'.json'),original)
            os.replace(str(path),str(folder/name))
            store.save(revised,'Report restyled to the Signature Edition; saved analysis and assessment date preserved')
        return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='data/records',type=Path)
    args=parser.parse_args(argv)
    store=Store(args.root)
    updated=0
    for path in sorted(args.root.glob('*/record.json')):
        changed=restyle_report(store,path.parent.name)
        updated+=int(changed)
        print(path.parent.name+(': updated' if changed else ': already styled or no report'))
    print('Updated %s saved reports.'%updated)


if __name__=='__main__':
    main()
