import os
import requests
from iantirta.media import BaseHTTP

class IanTirtaAPI(BaseHTTP):
    endpoint: str = 'https://www.iantirta.com'

    def __init__(
        self,
        api_url: str,
        api_token: str,
        *args,
        db_name: str | None = None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)

        if api_url is not None:
            self.endpoint = api_url

        self.db_name = db_name
        self.api_token = api_token

    def build_headers(self):
        headers = {
            'Authorization': f'bearer {self.api_token}',
            "User-Agent": "IantirtaAPI " + requests.utils.default_user_agent(),
            "Content-Type": "application/json",
        }
        if self.db_name:
            headers['X-Sigil-Database'] = self.db_name
        return headers

    def raise_for_status(self, res):
        try:
            res.raise_for_status()
        except Exception:
            raise

        res = res.json()
        if isinstance(res, dict) and (error := res.get("error")):
            error_data = error.get("data", {})
            raise OSError(
                f"\nIantirta API Error ({error.get('code')}) {error.get('message')}:\n"
                f"ErrorType: {error_data.get('name')}\n"
                f"Message: {error_data.get('message')}\n"
                f"Traceback: {error_data.get('debug')}"
            )

    def make_json_request(
        self,
        method: str = 'GET',
        path: str = '',
        params: dict | None = None,
    ):
        headers = self.build_headers()
        res = self.request(
            method,
            path,
            json=params,
            headers=headers
        )
        self.raise_for_status(res)
        return res.json()

    def test_connection(self):
        return self.make_json_request(
            'get',
            '/web/health'
        )

    def model_bridge(self, model, method):
        pass
        

if __name__ == '__main__':
    api = IanTirtaAPI(
        api_url='https://karaoke.iantirta.com',
        api_token=os.environ['IANTIRTA_API_TOKEN'],
        #db_name='karaoke'
    )
    print(api.test_connection())
    karaoke_ids = (api.make_json_request(
        'POST',
        '/json/2/karaoke.karaoke/search',
        {
            'domain': [
                ('status', '!=', 'completed'),
                ('karaoke_type', '=', 'basic'),
                '|',
                ('download_url', '!=', False),
                ('download_uris', '!=', False)
            ],
        }
    ))
    karaokes = api.make_json_request(
        'POST',
        '/json/2/karaoke.karaoke/read',
        {
            'ids': karaoke_ids,
            'fields': [
                'title',
                'download_url',
                'artist',
                'status',
                'download_uris'
            ]
        }
    )
    print(len(karaoke_ids))
    print(len(karaokes))
    urls = [k for k in karaokes if k['download_url'] and not k['download_uris']]
    uris = [k for k in karaokes if not k['download_url'] and k['download_uris']]
    boths = [k for k in karaokes if k['download_url'] and k['download_uris']]
    print(len(urls))
    print(len(uris))
    print(len(boths))
    failed = 0
    for k in boths:
        if isinstance(k['download_uris'], dict):
            metadata = k['download_uris']
            size = metadata['size']
            if size < 5 * 1024 * 1024:
                print(k)
                failed += 1
                res = api.make_json_request(
                    'POST',
                    '/json/2/karaoke.karaoke/write',
                    {
                        'ids': [k['id']],
                        'vals': {
                            'download_uris': False
                        }
                    }
                )
                print(res)
        else:
            metadata = k['download_uris']
            if isinstance(metadata, list):
                if len(metadata) > 1:
                    print('more than 1')
                elif len(metadata) == 1:
                    uri = metadata[0]
                    url = k['download_url']
                    if uri != url:
                        print('different url', uri, url)
                        res = api.make_json_request(
                            'POST',
                            '/json/2/karaoke.karaoke/write',
                            {
                                'ids': [k['id']],
                                'vals': {
                                    'download_uris': False
                                }
                            }
                        )
                    else:
                        print(uri)
                else:
                    print('is it zero')
            else:
                print('not a list')
    print(failed)
    for k in uris:
        metadata = k['download_uris']
        if isinstance(metadata, dict):
            print(k)
        elif isinstance(metadata, list):
            if len(metadata) > 1:
                print(k)
            elif len(metadata) == 1:
                uri = metadata[0]
                if 'drive' in uri:
                    res = api.make_json_request(
                        'POST',
                        '/json/2/karaoke.karaoke/write',
                        {
                            'ids': [k['id']],
                            'vals': {
                                'download_url': uri,
                                'download_uris': False
                            }
                        }
                    )
                    print(res)
                else:
                    print('not a drive')
            else:
                print('less than 1')
        else:
            print('not a list')

    for k in urls:
        # since this is not found in drive
        res = api.make_json_request(
                        'POST',
                        '/json/2/karaoke.karaoke/write',
                        {
                            'ids': [k['id']],
                            'vals': {
                                'download_url': False,
                                'download_uris': False
                            }
                        }
        )
        print(res)
