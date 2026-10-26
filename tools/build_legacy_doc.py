"""Build the pinned separate Antiword reader with the existing private MinGW toolchain."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

# ==========================================
# Function: Build/copy the private DOC converter and its complete corresponding source/license.
# Method: Verify the vendored archive and reuse the existing Home-native build cache; never install global tools.
# ==========================================
def build(bundle,compiler):
    root=Path(__file__).resolve().parents[1];vendor=root/'native/third_party/antiword';meta=json.loads((vendor/'SOURCE.json').read_text());archive=vendor/'source.tar.gz'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('Antiword source digest mismatch')
    base=root/'.runtime/windows-sdk/antiword';source=base/('antiword-'+meta['commit'])
    if not source.exists():
        base.mkdir(exist_ok=True)
        with tarfile.open(archive) as file:file.extractall(base,filter='data')
    cc=compiler/'x86_64-w64-mingw32-gcc';command=['make','-f','Makefile.cygming','-j4','CC='+str(cc),'LD='+str(cc),'CFLAGS=-O2 -D__CYGMING__ -DNDEBUG -Wno-implicit-function-declaration','LDFLAGS=-s']
    with (base/'build.log').open('w') as log:subprocess.run(command,cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
    runtime=bundle/'runtime';(runtime/'share/antiword').mkdir(parents=True,exist_ok=True);shutil.copy2(source/'antiword.exe',runtime/'bin/antiword.exe');shutil.copytree(source/'Resources',runtime/'share/antiword',dirs_exist_ok=True)
    docs=bundle/'docs/third_party/antiword';docs.mkdir(parents=True,exist_ok=True)
    for name in ('source.tar.gz','SOURCE.json','LICENSE','BUILD.md'):shutil.copy2(vendor/name,docs/name)
