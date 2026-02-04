#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "httpx",
#     "python-telegram-bot>=22.6",
# ]
# ///

"""
Send a message to a Telegram user, optionally to a specific topic in private chat.

Supports two backends:
  --via http   : direct HTTP requests via httpx (default)
  --via ptb    : python-telegram-bot library

Requires Bot API 9.3+ (topics in private chats).
The user must have enabled "Topics" mode in their private chat with the bot.

Usage:
    ./tg-send-topic.py --token BOT_TOKEN --listen
    ./tg-send-topic.py --token BOT_TOKEN --chat-id USER_ID "Hello world"
    ./tg-send-topic.py --via ptb --token BOT_TOKEN --chat-id USER_ID --thread-id 123 "Hello topic"
    ./tg-send-topic.py --token BOT_TOKEN --chat-id USER_ID --info

Environment variables BOT_TOKEN and CHAT_ID can be used instead of flags.
"""

import argparse
import asyncio
import json
import os
import sys


# --- HTTP backend ---


def http_call_api(token, method, **params):
    import httpx

    url = f'https://api.telegram.org/bot{token}/{method}'
    payload = {k: v for k, v in params.items() if v is not None}
    resp = httpx.post(url, json=payload)
    data = resp.json()
    if not data.get('ok'):
        print(f'API error: {data.get("description", "unknown error")}', file=sys.stderr)
        sys.exit(1)
    return data['result']


def http_me(token):
    result = http_call_api(token, 'getMe')
    print(json.dumps(result, indent=2, ensure_ascii=False))


def http_info(token, chat_id):
    result = http_call_api(token, 'getChat', chat_id=chat_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def http_listen(token):
    import httpx
    import time

    print('Listening for messages... Send a message to your bot in Telegram.')
    print('Press Ctrl+C to stop.\n')
    offset = None
    while True:
        params = {'timeout': 30}
        if offset is not None:
            params['offset'] = offset
        url = f'https://api.telegram.org/bot{token}/getUpdates'
        resp = httpx.post(url, json=params, timeout=35)
        data = resp.json()
        if not data.get('ok'):
            print(f'API error: {data.get("description", "unknown error")}', file=sys.stderr)
            time.sleep(1)
            continue
        for update in data['result']:
            offset = update['update_id'] + 1
            msg = update.get('message')
            if not msg:
                print(f'Update (no message): {json.dumps(update, indent=2, ensure_ascii=False)}')
                continue
            chat = msg['chat']
            print(f'--- Message from {chat.get("first_name", "")} {chat.get("last_name", "")} ---')
            print(f'  chat_id:           {chat["id"]}')
            print(f'  chat_type:         {chat["type"]}')
            if msg.get('message_thread_id'):
                print(f'  message_thread_id: {msg["message_thread_id"]}')
            if msg.get('is_topic_message'):
                print(f'  is_topic_message:  {msg["is_topic_message"]}')
            if msg.get('forum_topic_created'):
                print(f'  forum_topic_created: {json.dumps(msg["forum_topic_created"])}')
            text_content = msg.get('text', '')
            print(f'  text:              {text_content}')
            print()


def http_create_topic(token, chat_id, name):
    result = http_call_api(token, 'createForumTopic', chat_id=chat_id, name=name)
    print(f'Topic created!')
    print(f'  thread_id: {result["message_thread_id"]}')
    print(f'  name:      {result["name"]}')
    print(f'  icon_color: {result.get("icon_color")}')
    if result.get('is_name_implicit'):
        print(f'  is_name_implicit: {result["is_name_implicit"]}')


def http_send(token, chat_id, text, thread_id=None):
    result = http_call_api(token, 'sendMessage', chat_id=chat_id, text=text, message_thread_id=thread_id)
    print(f'Message sent! ID: {result["message_id"]}')
    if result.get('message_thread_id'):
        print(f'Thread ID: {result["message_thread_id"]}')
    if result.get('is_topic_message'):
        print(f'Is topic message: {result["is_topic_message"]}')


# --- python-telegram-bot backend ---


async def ptb_info(token, chat_id):
    import telegram

    bot = telegram.Bot(token)
    async with bot:
        chat = await bot.get_chat(chat_id)
        # convert to dict for consistent JSON output
        print(json.dumps(chat.to_dict(), indent=2, ensure_ascii=False))


async def ptb_send(token, chat_id, text, thread_id=None):
    import telegram

    bot = telegram.Bot(token)
    async with bot:
        kwargs = dict(chat_id=chat_id, text=text)
        if thread_id is not None:
            kwargs['message_thread_id'] = thread_id
        msg = await bot.send_message(**kwargs)
        print(f'Message sent! ID: {msg.message_id}')
        if msg.message_thread_id:
            print(f'Thread ID: {msg.message_thread_id}')
        if msg.is_topic_message:
            print(f'Is topic message: {msg.is_topic_message}')


# --- main ---


def main():
    parser = argparse.ArgumentParser(description='Send a message to a Telegram user via Bot API')
    parser.add_argument('text', nargs='?', help='Message text to send')
    parser.add_argument(
        '--via',
        choices=['http', 'ptb'],
        default='http',
        help='Backend: http (direct HTTP) or ptb (python-telegram-bot). Default: http',
    )
    parser.add_argument('--token', default=os.environ.get('BOT_TOKEN'), help='Bot token (or set BOT_TOKEN env var)')
    parser.add_argument(
        '--chat-id',
        type=int,
        default=int(os.environ.get('CHAT_ID', '0')) or None,
        help='User/chat ID (or set CHAT_ID env var)',
    )
    parser.add_argument('--thread-id', type=int, default=None, help='Topic thread ID for sending to a specific topic')
    parser.add_argument('--create-topic', metavar='NAME', help='Create a forum topic with the given name')
    parser.add_argument('--me', action='store_true', help='Call getMe and print bot info')
    parser.add_argument('--listen', action='store_true', help='Listen for incoming messages and print chat/thread IDs')
    parser.add_argument('--info', action='store_true', help='Show chat info (JSON) instead of sending a message')
    args = parser.parse_args()

    if not args.token:
        print('Error: --token or BOT_TOKEN env var is required', file=sys.stderr)
        sys.exit(1)

    if args.me:
        http_me(args.token)
        return

    if args.listen:
        http_listen(args.token)
        return

    if not args.chat_id:
        print('Error: --chat-id or CHAT_ID env var is required', file=sys.stderr)
        sys.exit(1)

    print(f'[backend: {args.via}]')

    if args.create_topic:
        http_create_topic(args.token, args.chat_id, args.create_topic)
        return

    if args.via == 'http':
        if args.info:
            http_info(args.token, args.chat_id)
        elif args.text:
            http_send(args.token, args.chat_id, args.text, args.thread_id)
        else:
            print('Error: provide message text or use --info', file=sys.stderr)
            sys.exit(1)
    else:
        if args.info:
            asyncio.run(ptb_info(args.token, args.chat_id))
        elif args.text:
            asyncio.run(ptb_send(args.token, args.chat_id, args.text, args.thread_id))
        else:
            print('Error: provide message text or use --info', file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
