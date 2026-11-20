"""Build a source-only handoff without keys, recordings, databases or model weights."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parent.parent
output=root.parent/'musiccraft-v0.2.zip'
excluded={'data','voice-data','modelsrc','.venvs','.git','__pycache__','.pytest_cache'}
with ZipFile(output,'w',ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if not path.is_file() or any(part in excluded for part in relative.parts):continue
        if path.name=='.env' or path.name.startswith('.env.') and path.name!='.env.example':continue
        if path.suffix in {'.pyc','.sqlite3','.log','.zip'} or path.name=='.DS_Store':continue
        archive.write(path,Path('musiccraft')/relative)
print(output)
