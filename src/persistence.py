"""File-only atomic outputs and content hashes. A complete marker is written last."""
import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

def atomic(path, text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def json_write(path,value):
    atomic(path,json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')

def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def csv_write(path,rows,fields):
    stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=fields)
    writer.writeheader(); writer.writerows(rows)
    atomic(path,stream.getvalue())
