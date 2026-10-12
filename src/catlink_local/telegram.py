"""Send-only Telegram delivery through the Bot API.

The bot may be shared with a conversational agent; this module never calls
getUpdates, so it does not compete with the agent for incoming messages.
"""
import json
from pathlib import Path
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _token(config):
    if config.get('token'):
        return config['token']
    return Path(config['token_file']).expanduser().read_text().strip()


def _call(config, method, data, content_type):
    request = Request(f"https://api.telegram.org/bot{_token(config)}/{method}", data=data,
                      headers={'Content-Type': content_type}, method='POST')
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        # The error body names the problem (wrong chat id, bot blocked); keep the token out.
        detail = error.read()[:200].decode(errors='replace')
        error.close()
        raise OSError(f'telegram {method} failed: {error.code} {detail}') from None
    if not result.get('ok'):
        raise OSError(f"telegram {method} failed: {result.get('description')}")
    return result


def send_text(config, text):
    body = json.dumps({'chat_id': config['chat_id'], 'text': text,
                       'disable_web_page_preview': True}).encode()
    return _call(config, 'sendMessage', body, 'application/json')


def send_photo(config, png, caption):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (('chat_id', str(config['chat_id'])), ('caption', caption[:1024])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="visit.png"\r\n'
                 'Content-Type: image/png\r\n\r\n'.encode() + png + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return _call(config, 'sendPhoto', b''.join(parts), f'multipart/form-data; boundary={boundary}')


def updates(config, offset, timeout=25):
    """Long-poll incoming messages (only for a bot owned by this controller)."""
    query = f'getUpdates?timeout={timeout}&allowed_updates=%5B%22message%22%5D'
    if offset is not None:
        query += f'&offset={offset}'
    request = Request(f"https://api.telegram.org/bot{_token(config)}/{query}")
    try:
        with urlopen(request, timeout=timeout + 10) as response:
            result = json.loads(response.read())
    except HTTPError as error:
        detail = error.read()[:200].decode(errors='replace')
        error.close()
        raise OSError(f'telegram getUpdates failed: {error.code} {detail}') from None
    return result.get('result', [])
