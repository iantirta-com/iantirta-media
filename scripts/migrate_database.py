import os
import shutil
import threading
from pathlib import Path

import requests
from iantirta.karaoke.api.karaoke_iantirta_worker import KaraokeWorker

iantirta_api_token = os.environ['IANTIRTA_KARAOKE_API_TOKEN']
base_domain = 'https://karaoke.iantirta.com/json/2'
_lock = threading.Lock()

def get_karaoke_tasks():
    headers = {
        'Authorization': f'bearer {iantirta_api_token}'
    }
    params = {
        'domain': [
            ('status', '=', 'waiting'),
            ('download_uris', '=', False),
            ('download_url', '!=', False)
        ]
    }
    res = requests.post(f'{base_domain}/karaoke.karaoke/search', json=params, headers=headers)
    res.raise_for_status()
    ids = res.json()

    res_read = requests.post(f'{base_domain}/karaoke.karaoke/read', headers=headers, json={
        'ids': ids,
        'fields': ['title', 'download_url', 'artist']
    })
    res_read.raise_for_status()
    tasks = res_read.json()
    print(len(tasks))
    return tasks

def migrate_drive_to_hf(api, tasks):
    temp_dir = Path("iantirta/migration")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    buffer_tasks = []

    def _flush():
        with _lock:
            if api.storage_api.staging_dir.exists():
                api.storage_api.upload_folder(folder_path=api.storage_api.staging_dir)

            api.api.make_json_request(
                'karaoke/task/update',
                {'tasks': buffer_tasks},
            )
            shutil.rmtree(api.storage_api.staging_dir, ignore_errors=True)
            shutil.rmtree(temp_dir, ignore_errors=True)
            buffer_tasks.clear()

    def _should_flush():
        if len(buffer_tasks) > 100:
            return True

    for task in tasks:
        task_id = task['id']
        title = task['title']
        artist = task['artist']
        gdrive_url = task['download_url']

        temp_video_path = temp_dir / f"{title}.mkv"
        with requests.get(gdrive_url, stream=True) as r:
            r.raise_for_status()
            with open(temp_video_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            chunk_metadata = api.storage_api.make_chunk_file(
                src_path=temp_video_path, 
                target_path=artist
            )
            chunk_metadata['provider'] = 'hf_dataset'
            
            task['download_uris'] = chunk_metadata
            buffer_tasks.append(task)
            print(f"Successfully download Task {task_id} to temp and make chunk_file.")

        if _should_flush():
            _flush()

    if buffer_tasks:
        _flush()

if __name__ == "__main__":
    api = KaraokeWorker(
        api_url=IANTIRTA_URL.replace('http://', 'https://'),
        api_token=IANTIRTA_API_KEY,
        worker_id=WORKER_ID,
        storage_options=STORAGE_OPTIONS,
        process_task_limit=None,
        max_gpu_pool=1,
        claim_task_domain=[
            ('status', '==', 'waiting'),
            ('download_uris', '==', False,),
            ('download_url', '!=', False)
        ]
    )
    tasks = get_karaoke_tasks()
    migrate_drive_to_hf(api, tasks)
