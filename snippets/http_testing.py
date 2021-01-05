import logging
import json
import requests


class HTTPClient:
    def __init__(self, base_uri, headers=None):
        self.base_uri = base_uri
        self.headers = headers or {}

    def request(self, method, uri, *args, **kwargs):
        url = self.base_uri + uri
        if 'headers' in kwargs:
            headers = dict(self.headers)
            headers.update(kwargs['headers'])
            kwargs['headers'] = headers
        else:
            if self.headers:
                kwargs['headers'] = self.headers

        if 'json_data' in kwargs:
            kwargs['data'] = json.dumps(kwargs.pop('json_data'))
            if 'headers' in kwargs:
                kwargs['headers'].update({
                    'Content-Type': 'application/json',
                })
        logging.debug(
            'HTTPClient request, %s, %s, %s, %s',
            method, url, args, kwargs)
        resp = getattr(requests, method)(url, *args, **kwargs)
        logging.info('Response: %s, %s', resp.status_code, resp.content[:100])
        return resp

    def get(self, uri, *args, **kwargs):
        return self.request('get', uri, *args, **kwargs)

    def post(self, uri, *args, **kwargs):
        return self.request('post', uri, *args, **kwargs)

    def put(self, uri, *args, **kwargs):
        return self.request('put', uri, *args, **kwargs)

    def delete(self, uri, *args, **kwargs):
        return self.request('delete', uri, *args, **kwargs)
