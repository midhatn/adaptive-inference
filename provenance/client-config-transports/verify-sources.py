"""Verify archived adapter inputs without Git or network access."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def verify():
    manifest=json.loads((HERE/'source-manifest.json').read_text(encoding='utf-8'))
    assert manifest['schema']=='adaptive-inference.client-source-closure.v1'
    total=0
    for repo in manifest['repositories']:
        root=(HERE/'sources'/repo['id']).resolve()
        assert any(f['kind']=='license' for f in repo['files'])
        for row in repo['files']:
            target=(root/row['path']).resolve()
            if root not in target.parents:raise ValueError('Source path escapes repository')
            data=target.read_bytes()
            if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
                raise ValueError('Source hash mismatch: '+repo['id']+'/'+row['path'])
            total+=1
    return total
if __name__=='__main__':print(json.dumps({'passed':True,'verified_files':verify()}))
