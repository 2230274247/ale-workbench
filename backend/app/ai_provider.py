"""Bounded OpenAI-compatible HTTP adapter. No SDK, redirects, proxy or unsafe retries."""
from copy import deepcopy
import ipaddress
import json
import re
import socket
import time
import queue
import threading
from urllib.parse import urlsplit
import httpx

MAX_RESPONSE_BYTES = 262144
MAX_REQUEST_BYTES = 48000
CALL_SECONDS = 25


class DeadlineStream:
    """Bound every socket operation, including headers/TLS, to one HTTP deadline."""
    def __init__(self, stream, deadline):
        self.stream, self.deadline = stream, deadline

    def remaining(self, timeout):
        left = self.deadline - time.monotonic()
        if left <= 0: raise httpx.ReadTimeout('Provider deadline exceeded')
        return min(left, timeout) if timeout is not None else left

    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, timeout=self.remaining(timeout))

    def write(self, buffer, timeout=None):
        return self.stream.write(buffer, timeout=self.remaining(timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return DeadlineStream(self.stream.start_tls(ssl_context, server_hostname, self.remaining(timeout)), self.deadline)

    def get_extra_info(self, info): return self.stream.get_extra_info(info)
    def close(self): self.stream.close()


class DeadlineBackend:
    def __init__(self, backend, deadline):
        self.backend, self.deadline = backend, deadline

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        left = self.deadline-time.monotonic()
        if left <= 0: raise httpx.ConnectTimeout('Provider deadline exceeded')
        stream = self.backend.connect_tcp(host, port, min(timeout or left, left), local_address, socket_options)
        return DeadlineStream(stream, self.deadline)

    def sleep(self, seconds):
        raise ProviderError('provider_timeout')  # no retry/backoff in this adapter


class ProviderError(Exception):
    def __init__(self, code='provider_unavailable', uncertain=True):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def validate_endpoint(value):
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment
                or p.port not in (None, 443) or '\\' in value or '%' in p.netloc
                or not re.fullmatch(r'[A-Za-z0-9.:-]+|\[[A-Fa-f0-9:]+\]', p.netloc)
                or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/*', p.path)):
            raise ValueError()
        host = p.hostname.lower()
        if host == 'localhost' or '.' not in host and ':' not in host:
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global: raise ValueError()
        except ValueError:
            # Distinguish an invalid/non-public literal from a DNS hostname.
            if ':' in host or re.fullmatch(r'[0-9.]+', host): raise ValueError()
        return value.rstrip('/')
    except (ValueError, TypeError):
        raise ValueError('A public HTTPS provider endpoint is required') from None


def validate_provider_options(base_url, options):
    # Match the official hostname, never provider labels or changing model IDs.
    if urlsplit(base_url).hostname == 'api.deepseek.com' and options != {'thinking': {'type': 'disabled'}}:
        raise ValueError('api.deepseek.com requires provider_options thinking.type disabled for this nonthinking flow')


def public_addresses(host):
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError()
        return addresses
    except (OSError, ValueError):
        raise ProviderError('endpoint_not_public', uncertain=False) from None


class Provider:
    # Tests inject MockTransport and a deterministic PUBLIC DNS resolver, never loopback.
    def __init__(self, transport=None, resolver=public_addresses):
        self.transport = transport
        self.resolver = resolver

    def request(self, config, key, path, payload=None):
        if config.get('_external_send_allowed') is False:
            raise ProviderError('external_send_denied', False)
        started = time.monotonic()
        deadline = min(started + CALL_SECONDS, config.get('_turn_deadline', started + CALL_SECONDS))
        base = validate_endpoint(config['base_url'])
        url = httpx.URL(base + path)
        host = url.host
        # OS DNS may ignore socket timeouts. Bound its wait; the daemon can only
        # resolve a hostname, never send HTTP or use the credential.
        resolved = queue.Queue(maxsize=1)
        def resolve():
            try: resolved.put((True, self.resolver(host)))
            except Exception: resolved.put((False, None))
        threading.Thread(target=resolve, daemon=True).start()
        try:
            valid, addresses = resolved.get(timeout=max(0.001, min(5, deadline-time.monotonic())))
        except queue.Empty:
            raise ProviderError('provider_dns_timeout', False) from None
        if not valid: raise ProviderError('endpoint_not_public', False)
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise ProviderError('endpoint_not_public', False)
        # Pin the vetted address, retain TLS hostname verification/SNI and HTTP Host.
        target = url.copy_with(host=addresses[0])
        content = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode() if payload is not None else None
        if content and len(content) > MAX_REQUEST_BYTES: raise ProviderError('input_limit', False)
        if time.monotonic() >= deadline: raise ProviderError('provider_timeout', False)
        transport = self.transport
        if transport is None:
            # httpx exposes no absolute synchronous deadline; wrap httpcore's
            # socket backend so slow headers and slow chunks cannot renew it.
            from httpcore import SyncBackend
            transport = httpx.HTTPTransport(retries=0)
            transport._pool._network_backend = DeadlineBackend(SyncBackend(), deadline)
        try:
            if config.get('_before_send'): config['_before_send']()
            with httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                              timeout=httpx.Timeout(25, connect=5), limits=httpx.Limits(max_connections=1)) as client:
                with client.stream('POST' if payload is not None else 'GET', target,
                                   headers={'Authorization': 'Bearer ' + key, 'Host': host, 'Content-Type': 'application/json',
                                            'Accept-Encoding': 'identity'},
                                   content=content, extensions={'sni_hostname': host}) as response:
                    if response.status_code != 200:
                        # Classify by status only; upstream bodies may echo credentials
                        # or database excerpts. Unknown/5xx failures remain charge-uncertain.
                        codes = {400: 'provider_parameter_invalid', 401: 'provider_auth_failed',
                                 402: 'provider_insufficient_balance', 403: 'provider_permission_denied',
                                 422: 'provider_parameter_invalid', 429: 'provider_rate_limited'}
                        code = codes.get(response.status_code, 'provider_unavailable' if response.status_code >= 500 else 'provider_rejected')
                        raise ProviderError(code, uncertain=response.status_code not in codes)
                    # Never invoke HTTPX's content decoder: even a tiny gzip body
                    # can expand far beyond our cap before iter_bytes yields it.
                    if response.headers.get('Content-Encoding', 'identity').strip().lower() != 'identity':
                        raise ProviderError('provider_invalid_response')
                    # MockTransport may return an already buffered Response(json=...).
                    # Only access content in that case; live streaming content is unread.
                    chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
                    raw = bytearray()
                    for chunk in chunks:
                        if time.monotonic() >= deadline: raise ProviderError('provider_timeout')
                        if len(chunk) > MAX_RESPONSE_BYTES - len(raw): raise ProviderError('response_limit')
                        # iter_raw(chunk_size=...) buffers/copies an entire transport
                        # chunk inside HTTPX. Check its length first, then copy bounded
                        # views ourselves, including the already-buffered mock path.
                        view = memoryview(chunk)
                        for offset in range(0, len(view), 16384):
                            raw.extend(view[offset:offset + 16384])
                    data = json.loads(raw)
                    if not isinstance(data, dict): raise ValueError()
                    return data
        except ProviderError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # No automatic retries: even a provider's 5xx may have consumed tokens.
            raise ProviderError('provider_connect_failed', False) from None
        except (httpx.HTTPError, ValueError, OSError):
            raise ProviderError('provider_invalid_response') from None

    def models(self, config, key):
        data = self.request(config, key, '/models')
        if not isinstance(data.get('data'), list): raise ProviderError('provider_invalid_response')
        models, seen = [], set()
        for row in data['data'][:200]:
            value = row.get('id') if isinstance(row, dict) else None
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}', value) or value in seen:
                continue
            seen.add(value)
            model = {'id': value}
            # Optional documented GET /models fields, never inferred from an ID.
            # Drop arbitrary upstream fields and bound every displayed value.
            for field in ('name', 'owned_by'):
                text = row.get(field)
                if isinstance(text, str) and 0 < len(text) <= 128 and not any(ord(c) < 32 for c in text):
                    model[field] = text
            for field in ('context_window', 'max_output_tokens'):
                number = row.get(field)
                if type(number) is int and 0 < number <= 1000000000:
                    model[field] = number
            for field in ('input_modalities', 'output_modalities'):
                values = row.get(field)
                if isinstance(values, list) and len(values) <= 8 and all(isinstance(v, str) and re.fullmatch(r'[a-z_-]{1,32}', v) for v in values):
                    model[field] = values
            effort = row.get('effort')
            if isinstance(effort, dict):
                levels = effort.get('supported_levels')
                if isinstance(levels, list) and len(levels) <= 10 and all(isinstance(v, str) and re.fullmatch(r'[a-z_-]{1,32}', v) for v in levels):
                    model['effort'] = {'supported_levels': levels}
                    if effort.get('default_level') in levels:
                        model['effort']['default_level'] = effort['default_level']
            capabilities = row.get('api_capabilities')
            if isinstance(capabilities, dict):
                protocol = capabilities.get('anthropic_messages')
                if isinstance(protocol, dict) and protocol.get('system_prompt_update') in ('leading-only', 'in-history'):
                    model['api_capabilities'] = {'anthropic_messages': {'system_prompt_update': protocol['system_prompt_update']}}
            models.append(model)
        return models

    def completion(self, config, key, messages, tools=None, required=False):
        try:
            validate_provider_options(config['base_url'], config['provider_options'])
        except ValueError:
            raise ProviderError('provider_configuration_invalid', False) from None
        payload = {'model': config['model'], 'messages': messages,
                   'max_tokens': config['max_output_tokens'], 'stream': False}
        payload.update(config['provider_options'])
        if tools:
            payload['tools'] = deepcopy(tools)
            if urlsplit(config['base_url']).hostname == 'api.deepseek.com':
                # Stable non-strict function calling. DeepSeek strict requires /beta
                # and rejects schema keywords we use (e.g. maxLength). Do not change
                # the configured endpoint or silently claim beta strict support.
                # Server execute_tool always validates types, bounds and extra keys.
                for tool in payload['tools']:
                    tool['function'].pop('strict', None)
            payload['tool_choice'] = 'required' if required else 'auto'
        return self.request(config, key, '/chat/completions', payload)
