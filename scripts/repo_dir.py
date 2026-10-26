import subprocess
from pathlib import Path
import os

repo_dir = Path('D:/IANTIRTACOM/karaoke-archive')
assert repo_dir.exists()
os.chdir(repo_dir)

for artist_dir in repo_dir.iterdir():
    if (
        not artist_dir.is_dir()
        or artist_dir.name.startswith('.')
        or 'test' in artist_dir.name # Used for testing
    ): 
        continue

    print(artist_dir)
    print(len(list(artist_dir.iterdir())))
    for chunk_file in artist_dir.iterdir():
        if chunk_file.is_dir(): 
            continue

        prefix = chunk_file.name[:2]
        new_dir = artist_dir / prefix
        new_dir.mkdir(exist_ok=True)
        subprocess.run(['git', 'mv', chunk_file.as_posix(), (new_dir / chunk_file.name).as_posix()], check=True)