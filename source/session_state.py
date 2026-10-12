"""Track confirmed exports independently of navigation and auto-save activity."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from dataclasses import asdict
from engine import Adjustments


def conversion_signature(snapshot):
    photos={}
    for name,settings in sorted(snapshot.get('photos',{}).items()):
        values=asdict(Adjustments.from_dict(settings))
        values.pop('film_stock',None)  # Legacy label has no effect on processing.
        photos[name]=values
    recipe={'folder':snapshot.get('folder'),'photos':photos,
            'reference':snapshot.get('reference'),'reference_path':snapshot.get('reference_path'),
            'quality':snapshot.get('quality',95)}
    if any(a['color_mode']=='Roll color' for a in photos.values()):
        recipe['roll_model']=snapshot.get('roll_model')
    encoded=json.dumps(recipe,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def completion_matches(snapshot):
    record=snapshot.get('completed_export')
    if snapshot.get('app')!='Film Desk' or not snapshot.get('folder') or not snapshot.get('photos'):
        return False
    if not isinstance(record,dict) or record.get('schema')!=1:
        return False
    files=record.get('files')
    if not isinstance(files,dict) or not files or not isinstance(record.get('destination'),str):
        return False
    if any(not isinstance(name,str) or not isinstance(digest,str) or len(digest)!=64
           or any(c not in '0123456789abcdef' for c in digest) for name,digest in files.items()):
        return False
    try:
        return record.get('signature')==conversion_signature(snapshot)
    except (TypeError,ValueError,KeyError):
        return False


def jpeg_digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            result.update(block)
    return result.hexdigest()


def verified_existing_export(snapshot,destination,path):
    """Do not confuse an existing JPEG with a confirmed export of current edits."""
    if not completion_matches(snapshot):
        return False
    record=snapshot['completed_export']
    if str(Path(destination).resolve())!=record.get('destination'):
        return False
    expected=record['files'].get(Path(path).name)
    return bool(expected) and jpeg_digest(path)==expected


def finished_export_snapshot(snapshot,results,destination,cancelled):
    state=copy.deepcopy(snapshot)
    state['completed_export']=None
    selected={str(Path(state['folder'])/name) for name,a in state['photos'].items()
              if a.get('included',True) and str(Path(state['folder'])/name)!=state.get('reference_path')}
    if cancelled or not selected or len(results)!=len(selected):
        return state
    if {r.get('source') for r in results}!=selected:
        return state
    for result in results:
        if result.get('status')!='exported' and not(result.get('status')=='skipped' and result.get('verified')):
            return state
        if not result.get('sha256'):
            return state
    resolved=set()
    for result in results:
        if result.get('adjustments'):
            name=Path(result['source']).name
            state['photos'][name]=copy.deepcopy(result['adjustments'])
            resolved.add(result['source'])
    state['pending_crops']=[p for p in state.get('pending_crops',[]) if p not in resolved]
    state['completed_export']={'schema':1,'signature':conversion_signature(state),
        'destination':str(Path(destination).resolve()),
        'files':{Path(r['destination']).name:r['sha256'] for r in results}}
    return state
