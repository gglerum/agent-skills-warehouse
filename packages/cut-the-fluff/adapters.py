"""Shape-based local JSONL adapters. No runtime or command execution."""
import json


class Unsupported(ValueError):
    pass


# Audit-wide notes that cannot hide tool usage; they never make a session partial.
INFORMATIONAL = {'ignored_bookkeeping_record', 'ignored_request_copy', 'ignored_usage_summary', 'glob_matched_current_tree',
                 'external_glob_not_listed', 'usage_not_yet_reported'}
# Codex item_completed types. Only UserMessage, AgentMessage and FileChange were seen
# in a real rollout; the rest follow the app-server item names. Unknown types stay gaps.
CODEX_TEXT_ITEMS = {'UserMessage', 'AgentMessage', 'Reasoning', 'Plan', 'EnteredReviewMode', 'ExitedReviewMode'}
CODEX_TOOL_ITEMS = {'FileChange', 'CommandExecution', 'McpToolCall', 'CollabAgentToolCall', 'WebSearch', 'ImageView'}
# Gaps that only qualify file-read metrics; invocations and outcomes stay covered.
FILE_READ = {'unresolved_shell_access', 'unresolved_file_access', 'unresolved_shell_workdir'}


def tool_bearing(row):
    msg = row.get('message')
    content = msg.get('content') if isinstance(msg, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get('type') in ('tool_use', 'tool_result') for b in content)


def object_args(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


class Codex:
    name = 'codex'
    profile = 'codex-rollout-jsonl-1'

    def decode(self, row):
        if row.get('schema_version') not in (None, '1.0'):
            raise Unsupported('unsupported_format_version')
        kind, p = row.get('type'), row.get('payload')
        if not isinstance(p, dict):
            raise Unsupported('payload_shape')
        meta, events, gaps = {}, [], []
        if kind == 'session_meta':
            meta = dict(id=p.get('id'), cwd=p.get('cwd'), parent=p.get('parent_session_id'))
            source = p.get('source')
            if isinstance(source, dict):
                sub = source.get('subagent', {})
                spawn = sub.get('thread_spawn', {}) if isinstance(sub, dict) else {}
                if isinstance(spawn, dict):
                    meta['parent'] = spawn.get('parent_thread_id', meta['parent'])
        elif kind == 'turn_context':
            meta = dict(cwd=p.get('cwd'))
        elif kind == 'compacted':
            gaps.append('compaction')
        elif kind == 'world_state' and set(p) <= {'full', 'state'} and isinstance(p.get('state'), dict):
            gaps.append('ignored_bookkeeping_record')
        elif kind == 'token_usage_record':
            measurements = numeric_measurements(p.get('usage'))
            if measurements:
                meta['mirror_usage'] = json.dumps(measurements, sort_keys=True)
                gaps.append('ignored_usage_summary')
            else:
                gaps.append('missing_usage_fields')
        elif kind == 'response_item':
            t = p.get('type')
            if t in ('function_call', 'custom_tool_call'):
                events.append(dict(kind='call', call=p.get('call_id'), tool=p.get('name'),
                                   args=object_args(p.get('arguments', p.get('input')))))
            elif t in ('function_call_output', 'custom_tool_call_output'):
                output = p.get('output')
                success = None
                if isinstance(output, dict):
                    if type(output.get('exit_code')) is int:
                        success = output['exit_code'] == 0
                    elif type(output.get('success')) is bool:
                        success = output['success']
                # Text output alone does not establish successful execution.
                events.append(dict(kind='result', call=p.get('call_id'), success=success))
            elif t not in ('message', 'reasoning', 'web_search_call', 'local_shell_call'):
                gaps.append('unsupported_response_item')
            elif t in ('web_search_call', 'local_shell_call'):
                gaps.append('unsupported_native_tool')
        elif kind == 'event_msg':
            t = p.get('type')
            if t in ('task_complete', 'turn_aborted'):
                events.append(dict(kind='end'))
            elif t == 'token_count' and 'info' in p and p['info'] is None:
                # Codex writes rate-limit updates before the first usage of a turn
                # with info: null. There is no usage to count, and nothing is lost.
                gaps.append('usage_not_yet_reported')
            elif t == 'token_count':
                info = p.get('info')
                usage = info.get('last_token_usage') if isinstance(info, dict) else None
                measurements = numeric_measurements(usage)
                if measurements:
                    meta['canonical_usage'] = json.dumps(measurements, sort_keys=True)
                events.append(dict(kind='telemetry', component='runtime:usage', basis='direct',
                                   measurements=measurements))
                if not isinstance(p.get('info'), dict):
                    gaps.append('missing_usage_fields')
            elif t in ('context_compacted', 'compaction'):
                gaps.append('compaction')
            elif t == 'thread_settings_applied' and isinstance(p.get('thread_settings'), dict):
                gaps.append('ignored_bookkeeping_record')
            elif t == 'item_completed' and isinstance(p.get('item'), dict):
                # Native file changes have no call_id here. Do not guess which
                # response_item they mirror or manufacture a second invocation.
                item = p['item'].get('type')
                if item in CODEX_TOOL_ITEMS:
                    gaps.append('unsupported_native_tool')
                elif item == 'ContextCompaction':
                    gaps.append('compaction')
                elif item not in CODEX_TEXT_ITEMS:
                    gaps.append('unknown_native_item')
            elif t not in ('user_message', 'agent_message', 'agent_reasoning', 'task_started',
                           'item_completed', 'item_started'):
                gaps.append('unsupported_event_msg')
        else:
            gaps.append('unsupported_record')
        return meta, events, gaps


class Claude:
    name = 'claude'
    profile = 'claude-message-jsonl-1'

    def decode(self, row):
        if row.get('schema_version') not in (None, '1.0'):
            raise Unsupported('unsupported_format_version')
        meta = dict(id=row.get('sessionId'), cwd=row.get('cwd'), parent=row.get('parentSessionId'))
        agent = row.get('agentId')
        if agent and meta['id']:
            meta['parent'] = meta['id']
            meta['native_id'] = meta['id']
            meta['id'] += '/agent:' + str(agent)
        events, gaps = [], []
        kind = row.get('type')
        if kind in ('assistant', 'user'):
            msg = row.get('message')
            if not isinstance(msg, dict):
                raise Unsupported('message_shape')
            content = msg.get('content')
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        gaps.append('unsupported_content')
                    elif block.get('type') == 'tool_use':
                        events.append(dict(kind='call', call=block.get('id'), tool=block.get('name'),
                                           args=object_args(block.get('input'))))
                    elif block.get('type') == 'tool_result':
                        error = block.get('is_error', False)
                        events.append(dict(kind='result', call=block.get('tool_use_id'),
                                           success=not error if type(error) is bool else None))
                    elif block.get('type') not in ('text', 'thinking', 'redacted_thinking', 'image'):
                        gaps.append('unsupported_content')
            elif not isinstance(content, str):
                gaps.append('unsupported_content')
            if kind == 'assistant' and msg.get('stop_reason') == 'end_turn':
                events.append(dict(kind='end'))
        elif kind == 'system' and row.get('subtype') == 'compact_boundary':
            gaps.append('compaction')
        elif kind == 'summary':
            gaps.append('compaction')
        elif kind == 'api-request-blob':
            # Copy of the request sent to the API. Its tool IDs must repeat this file's
            # conversation; the reader checks that and otherwise records a session gap.
            msg = row.get('message')
            content = msg.get('content') if isinstance(msg, dict) else None
            meta['mirror_calls'] = {b.get('id') if b.get('type') == 'tool_use' else b.get('tool_use_id')
                                    for b in content if isinstance(b, dict) and
                                    b.get('type') in ('tool_use', 'tool_result')} if isinstance(content, list) else set()
            gaps.append('ignored_request_copy')
        elif kind not in ('progress', 'file-history-snapshot', 'queue-operation', 'last-prompt'):
            # Hosts add bookkeeping records (titles, modes, timings, request metadata).
            # Only records that could carry tool calls/results degrade session coverage.
            known_shape = isinstance(kind, str) and kind and not tool_bearing(row)
            gaps.append('ignored_bookkeeping_record' if known_shape else 'unsupported_record')
        return meta, events, gaps


class Supplement:
    """Deliberately selected exports, never automatic telemetry collection."""
    name = 'supplement'
    profile = 'ctf-evidence-1'

    def decode(self, row):
        if row.get('format') != self.profile or row.get('kind') not in ('handoff', 'telemetry'):
            raise Unsupported('unsupported_export')
        meta = dict(id=row.get('session_id'), cwd=row.get('project'), parent=row.get('parent_session_id'))
        event = dict(kind=row['kind'], component=row.get('component'),
                     state=row.get('state', 'unknown') if row['kind'] == 'handoff' else 'unknown',
                     basis='reported' if row['kind'] == 'handoff' else 'direct',
                     measurements=numeric_measurements(row.get('measurements')))
        if event['state'] not in ('configured', 'advertised', 'loaded', 'invoked', 'successful', 'unknown'):
            raise Unsupported('unsupported_claim_state')
        return meta, [event], ['reported_claim'] if row['kind'] == 'handoff' else []


def numeric_measurements(value):
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if k in
            ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_read_tokens', 'duration_ms')
            and type(v) in (int, float) and 0 <= v < 1e18}
