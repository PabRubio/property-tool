#!/usr/bin/env python3
"""Offline app-server peer: exercises the application's real stdio transport."""
import json
import os
import sys
import time


def emit(value):
    print(json.dumps(value), flush=True)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    params = message.get('params', {})
    mode = os.environ.get('PROPERTY_TEST_CODEX_MODE', '')
    result = {}
    if method == 'account/read':
        result = {'account': {'type': 'apiKey' if mode == 'api_key' else 'chatgpt'}, 'requiresOpenaiAuth': True}
    elif method == 'config/read':
        result = {'config': {'mcp_servers': {'unrelated': {'url': 'https://example.com/mcp'}}}}
    elif method == 'thread/start':
        config = params['config']
        isolated = (config.get('mcp_servers.unrelated.enabled') is False
                    and config.get('features.plugins') is False
                    and config.get('skills.include_instructions') is False
                    and config.get('features.shell_tool') is False
                    and config.get('features.js_repl') is False
                    and config.get('features.memory_tool') is False
                    and config.get('notify') == []
                    and params.get('sandbox') == 'read-only')
        if not isolated:
            emit({'id': message['id'], 'error': {'message': 'Runtime was not isolated'}})
            continue
        result = {'thread': {'id': 'thread-test'}, 'model': 'test-model'}
    elif method == 'turn/start':
        emit({'id': message['id'], 'result': {'turn': {'id': 'turn-test', 'status': 'inProgress'}}})
        if mode == 'timeout':
            time.sleep(30)
            continue
        if mode == 'eof':
            sys.exit(0)
        if mode == 'research':
            emit({'method': 'item/completed', 'params': {'threadId': 'thread-test', 'turnId': 'turn-test', 'item': {
                'id': 'call-1', 'type': 'mcpToolCall', 'server': 'firecrawl', 'tool': 'firecrawl_scrape',
                'arguments': {'url': 'https://agent.example/house'}, 'status': 'completed',
                'result': {'content': [{'type': 'text', 'text': json.dumps({'success': True, 'markdown': 'Whole house £1,400 pcm', 'metadata': {'sourceURL': 'https://agent.example/house'}})}]}}}})
        emit({'method': 'item/completed', 'params': {'threadId': 'thread-test', 'turnId': 'turn-test', 'item': {
            'id': 'comment', 'type': 'agentMessage', 'phase': 'commentary', 'text': 'Checking the evidence.'}}})
        emit({'method': 'item/completed', 'params': {'threadId': 'thread-test', 'turnId': 'turn-test', 'item': {
            'id': 'answer', 'type': 'agentMessage', 'phase': 'final_answer', 'text': '{"answer": "ok"}'}}})
        emit({'method': 'turn/completed', 'params': {'threadId': 'thread-test', 'turn': {
            'id': 'turn-test', 'status': 'failed' if mode == 'failed' else 'completed',
            'error': {'message': 'Usage limit reached'} if mode == 'failed' else None}}})
        continue
    if 'id' in message:
        emit({'id': message['id'], 'result': result})
