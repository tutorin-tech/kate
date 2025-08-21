"""The module contains the unit tests from the original Tornado source code."""

# ruff: noqa: FBT003, SLF001

import asyncio
import socket
import struct
import unittest
from unittest.mock import AsyncMock, Mock, patch

from kate.core.websocket import (
    WebSocketClosedError,
    WebSocketHandler,
    WebSocketProtocol13,
    _DecompressTooLargeError,
)
from kate.core.websocket import _PerMessageDeflateCompressor as Compressor
from kate.core.websocket import _PerMessageDeflateDecompressor as Decompressor
from kate.test.core.base import (
    BaseWebSocketTestCase,
    DummyServer,
    get_params,
)


class _BaseTestHandler(WebSocketHandler):
    """Minimal WebSocketHandler subclass used across the tests."""

    def __init__(self, headers, reader, writer, server, *, close_future=None):
        super().__init__(headers, reader, writer, server)
        self.close_future = close_future
        self.messages = []

    async def on_message(self, message):
        self.messages.append(message)

    async def on_close(self):
        if self.close_future is not None and not self.close_future.done():
            self.close_future.set_result((self.close_code, self.close_reason))


class _EchoHandler(_BaseTestHandler):
    async def on_message(self, message):
        await self.write_message(message, isinstance(message, bytes))


class _RenderMessageHandler(_BaseTestHandler):
    async def on_message(self, message):
        await self.write_message(f'<b>{message}</b>')


class _ErrorInOnMessageHandler(_BaseTestHandler):
    async def on_message(self, _message):  # noqa: PLR6301
        raise ZeroDivisionError


class _CoroutineMessageHandler(_BaseTestHandler):
    def __init__(self, headers, reader, writer, server):
        super().__init__(headers, reader, writer, server)
        self.call_order = []

    async def on_message(self, message):
        self.call_order.append(('start', message))
        await asyncio.sleep(0)
        self.call_order.append(('end', message))
        await self.write_message(message)


class _NativeCoroutineHandler(_BaseTestHandler):
    def __init__(self, headers, reader, writer, server):
        super().__init__(headers, reader, writer, server)
        self.received = []

    async def on_message(self, message):
        self.received.append(message)


class _SubprotocolHandler(_BaseTestHandler):
    def __init__(self, headers, reader, writer, server):
        super().__init__(headers, reader, writer, server)
        self.select_called = False

    def select_subprotocol(self, subprotocols):
        self.select_called = True
        if 'goodproto' in subprotocols:
            return 'goodproto'
        return None


class WebSocketTest(BaseWebSocketTestCase):  # noqa: PLR0904
    """Tests adapted from Tornado's WebSocketTest suite."""

    async def test_http_request_returns_400(self):
        """The handler should return 400 when the Upgrade header is not set to WebSocket."""
        headers = dict(self.headers, Upgrade='http')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer,
            400,
            'Can "Upgrade" only to "WebSocket".',
        )

    async def test_missing_websocket_key_returns_400(self):
        """The handler should return 400 when the Sec-WebSocket-Key header is missing."""
        headers = dict(self.headers)
        headers.pop('Sec-WebSocket-Key')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 400, 'Missing/Invalid WebSocket headers',
        )

    async def test_bad_websocket_version_returns_426(self):
        """The handler should return 426 when the Sec-WebSocket-Version header is unsupported."""
        headers = dict(self.headers, **{'Sec-WebSocket-Version': '12'})
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer,
            code=426,
            message='Upgrade Required',
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'Sec-WebSocket-Version': '7, 8, 13',
            },
        )

    async def test_basic_text_write(self):
        """The echo handler should forward text frames with the binary flag disabled."""
        handler = _EchoHandler(self.headers, self.reader, self.writer, self.server)

        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        handler.ws_connection = connection

        await handler.write_message('hello')

        connection.write_message.assert_awaited_once_with('hello', binary=False)

    async def test_binary_message_handling(self):
        """The echo handler should forward binary payloads with the binary flag enabled."""
        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = connection

        payload = b'hello \xe9'
        await self.handler.write_message(payload, binary=True)

        connection.write_message.assert_awaited_once_with(payload, binary=True)

    async def test_unicode_message_handling(self):
        """The echo handler should forward Unicode messages as text frames."""
        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = connection

        await self.handler.write_message('hello')

        connection.write_message.assert_awaited_once_with('hello', binary=False)

    async def test_write_message_after_close_raises(self):
        """The handler should raise WebSocketClosedError when writing after
        the connection closes.
        """
        connection = AsyncMock()
        connection.is_closing = Mock(return_value=True)
        self.handler.ws_connection = connection

        with self.assertRaises(WebSocketClosedError):
            await self.handler.write_message('late message')

    async def test_render_message_handler_encodes_html(self):
        """The render handler should wrap incoming text in HTML before sending it."""
        handler = _RenderMessageHandler(self.headers, self.reader, self.writer, self.server)

        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        handler.ws_connection = connection

        await handler.on_message('hello')

        connection.write_message.assert_awaited_once_with('<b>hello</b>', binary=False)

    async def test_error_in_on_message_propagates(self):
        """The handler should propagate exceptions raised inside on_message."""
        handler = _ErrorInOnMessageHandler(self.headers, self.reader, self.writer, self.server)
        with self.assertRaises(ZeroDivisionError):
            await handler.on_message('error')

    async def test_invalid_origin_rejected_with_403(self):
        """The handler should reject forbidden origins with a 403 HTTP error."""
        headers = dict(self.headers, Origin='http://evil.com')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 403, 'Cross origin websockets not allowed',
        )

    async def test_invalid_connection_header_rejected(self):
        """The handler should reject requests whose Connection header is not Upgrade."""
        headers = dict(self.headers, Connection='keep-alive')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 400, '"Connection" must be "Upgrade".',
        )

    async def test_server_close_reason(self):
        """The handler should forward server initiated close codes and reasons."""
        connection = AsyncMock()
        self.handler.ws_connection = connection

        await self.handler.close(1001, 'bye')

        connection.close.assert_awaited_once_with(1001, 'bye')
        self.assertIsNone(self.handler.ws_connection)

    async def test_on_ws_connection_close_records_code_and_reason(self):
        """The handler should record the close code and reason reported by the protocol."""
        await self.handler.on_ws_connection_close(1001, 'goodbye')

        self.assertEqual(self.handler.close_code, 1001)
        self.assertEqual(self.handler.close_reason, 'goodbye')

    async def test_write_message_fails_when_connection_closing(self):
        """The handler should raise WebSocketClosedError when the connection is closing."""
        connection = AsyncMock()
        connection.is_closing = Mock(return_value=True)
        self.handler.ws_connection = connection

        with self.assertRaises(WebSocketClosedError):
            await self.handler.write_message('late')

    async def test_get_preserves_path_arguments(self):
        """The handler should preserve positional and keyword arguments when get() is called."""
        protocol = AsyncMock()
        with patch.object(self.handler, 'get_websocket_protocol', return_value=protocol):
            await self.handler.get('arg', test='value')

        self.assertEqual(self.handler.open_args, ('arg',))
        self.assertEqual(self.handler.open_kwargs, {'test': 'value'})
        protocol.accept_connection.assert_awaited_once_with(self.handler)

    async def test_on_message_coroutines_run_sequentially(self):
        """The protocol should process coroutine on_message handlers sequentially."""
        handler = _CoroutineMessageHandler(self.headers, self.reader, self.writer, self.server)
        protocol = WebSocketProtocol13(handler, False, get_params(), self.reader, self.writer)

        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        handler.ws_connection = connection

        with patch('kate.core.websocket.asyncio.sleep', new_callable=AsyncMock) as sleep_mock:
            sleep_mock.return_value = None
            await protocol._handle_message(0x1, b'first')
            await protocol._handle_message(0x1, b'second')

        self.assertEqual(
            handler.call_order,
            [('start', 'first'), ('end', 'first'), ('start', 'second'), ('end', 'second')],
        )

    async def test_check_origin_valid_without_path(self):
        """The origin validator should accept hosts without paths."""
        self.assertTrue(self.handler.check_origin('http://example.com'))

    async def test_check_origin_valid_with_path(self):
        """The origin validator should accept hosts that include paths."""
        self.assertTrue(self.handler.check_origin('http://example.com/path'))

    async def test_check_origin_invalid_partial(self):
        """The origin validator should reject partial origins without a scheme."""
        self.assertFalse(self.handler.check_origin('example.com'))

    async def test_check_origin_invalid_origin(self):
        """The origin validator should reject explicitly forbidden origins."""
        self.assertFalse(self.handler.check_origin('http://evil.com'))

    async def test_check_origin_invalid_subdomain(self):
        """The origin validator should reject subdomains of the allowed host."""
        self.assertFalse(self.handler.check_origin('http://sub.example.com'))

    async def test_select_subprotocol_returns_match(self):
        """The handler should select the first supported subprotocol."""
        self.assertEqual(self.handler.select_subprotocol(['bad', 'good']), None)

        handler = _SubprotocolHandler(self.headers, self.reader, self.writer, self.server)
        self.assertEqual(handler.select_subprotocol(['badproto', 'goodproto']), 'goodproto')

    async def test_select_subprotocol_none_offered(self):
        """The handler should return None when no subprotocol is offered."""
        self.assertIsNone(self.handler.select_subprotocol([]))

    async def test_error_in_open_triggers_abort(self):
        """The protocol should abort the connection when open() raises an error."""
        async def failing_open(*_args, **_kwargs):  # noqa: RUF029
            raise RuntimeError

        with (
            patch.object(self.protocol, 'start_pinging', Mock()),
            patch.object(self.handler, 'open', AsyncMock(side_effect=failing_open)),
            patch.object(self.protocol, '_abort', AsyncMock()) as abort_mock,
        ):
            await self.protocol.accept_connection(self.handler)

        abort_mock.assert_awaited_once()

    async def test_error_in_async_open_triggers_abort(self):
        """The protocol should abort the connection when async open() fails."""
        async def async_failing_open(*_args, **_kwargs):
            await asyncio.sleep(0)
            raise RuntimeError

        with (
            patch.object(self.protocol, 'start_pinging', Mock()),
            patch.object(self.handler, 'open', AsyncMock(side_effect=async_failing_open)),
            patch.object(self.protocol, '_abort', AsyncMock()) as abort_mock,
        ):
            await self.protocol.accept_connection(self.handler)

        abort_mock.assert_awaited_once()

    async def test_set_nodelay_sets_tcp_flag(self):
        """The protocol should enable TCP_NODELAY on the underlying socket when requested."""
        server = DummyServer(with_socket=True)
        handler = _BaseTestHandler(self.headers, self.reader, self.writer, server)
        protocol = WebSocketProtocol13(handler, False, get_params(), self.reader, self.writer)

        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        handler.ws_connection = connection

        protocol.set_nodelay(True)
        await handler.write_message('hello')

        server.socket.setsockopt.assert_called_once_with(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1,
        )
        connection.write_message.assert_awaited_once_with('hello', binary=False)


class WebSocketNativeCoroutineTest(BaseWebSocketTestCase):
    """Tests adapted from Tornado's WebSocketNativeCoroutineTest."""

    async def test_native_coroutine_on_message(self):
        """The protocol should deliver messages to native coroutine handlers."""
        handler = _NativeCoroutineHandler(self.headers, self.reader, self.writer, self.server)
        protocol = WebSocketProtocol13(handler, False, get_params(), self.reader, self.writer)

        await protocol._handle_message(0x1, b'hello')

        self.assertEqual(handler.received, ['hello'])


class CompressionTests(unittest.TestCase):
    """Tests adapted from Tornado's compression scenarios."""

    def test_permessage_deflate_roundtrip(self):
        """The compressor and decompressor should round-trip payloads without loss."""
        compressor = Compressor(persistent=False, max_wbits=15)
        decompressor = Decompressor(
            persistent=False,
            max_wbits=15,
            max_message_size=4 * 1024,
        )
        payload = b'hello world' * 5

        compressed = compressor.compress(payload)
        decompressed = decompressor.decompress(compressed)

        self.assertEqual(decompressed, payload)

    def test_permessage_deflate_respects_size_limit(self):
        """The decompressor should enforce the configured message size limit."""
        compressor = Compressor(persistent=False, max_wbits=15)
        decompressor = Decompressor(
            persistent=False,
            max_wbits=15,
            max_message_size=8,
        )
        payload = b'a' * 64
        compressed = compressor.compress(payload)

        with self.assertRaises(_DecompressTooLargeError):
            decompressor.decompress(compressed)


class PingTests(BaseWebSocketTestCase):
    """Tests adapted from Tornado's ping-related test classes."""

    async def test_handler_ping_sends_frame(self):
        """The handler should instruct the connection to send ping frames."""
        connection = AsyncMock()
        connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = connection

        await self.handler.ping(b'data')

        self.handler.ws_connection.write_ping.assert_awaited_once_with(b'data')

    async def test_protocol_handles_ping_and_calls_handler(self):
        """The protocol should echo ping payloads and notify the handler."""
        self.handler.on_ping = AsyncMock()
        self.protocol._write_frame = AsyncMock()

        await self.protocol._handle_message(0x9, b'xyz')

        self.protocol._write_frame.assert_awaited_once_with(True, 0xA, b'xyz')
        self.handler.on_ping.assert_awaited_once_with(b'xyz')

    async def test_periodic_ping_closes_when_no_pong(self):
        """The protocol should close the connection when a pong is not received."""
        params = get_params(ping_interval=0.01, ping_timeout=0.01)
        protocol = WebSocketProtocol13(self.handler, False, params, self.reader, self.writer)

        with (
            patch.object(protocol, 'write_ping', AsyncMock()) as mock_write_ping,
            patch.object(protocol, 'close', AsyncMock()) as mock_close,
            patch('kate.core.websocket.asyncio.sleep', side_effect=[None, None]),
        ):
            await protocol.periodic_ping()

        mock_write_ping.assert_awaited_once()
        mock_close.assert_awaited_once_with(reason='ping timed out')

    def test_ping_sleep_time(self):
        """The ping sleep time helper should return the remaining interval."""
        sleep_time = self.protocol.ping_sleep_time(
            last_ping_time=100.0,
            interval=10.0,
            now=104.0,
        )
        self.assertEqual(sleep_time, 6.0)

    async def test_protocol_handles_manual_ping_and_pong(self):
        """The protocol should mark pongs as received and notify the handler."""
        self.handler.on_pong = AsyncMock()
        await self.protocol._handle_message(0xA, b'data')

        self.assertTrue(self.protocol._received_pong)
        self.handler.on_pong.assert_awaited_once_with(b'data')


class MaxMessageSizeTest(BaseWebSocketTestCase):
    """Tests adapted from Tornado's MaxMessageSizeTest."""

    async def test_large_frame_triggers_close(self):
        """The protocol should close the connection when a frame exceeds the maximum size."""
        params = get_params(max_message_size=4)
        protocol = WebSocketProtocol13(self.handler, False, params, self.reader, self.writer)

        with (
            patch.object(protocol, 'close', AsyncMock()) as mock_close,
            patch.object(protocol, '_abort', AsyncMock()) as mock_abort,
            patch.object(
                protocol, '_read_bytes', AsyncMock(side_effect=[struct.pack('BB', 0x81, 0x05)]),
            ),
        ):
            await protocol._receive_frame()

        mock_close.assert_awaited_once_with(1009, 'message too big')
        mock_abort.assert_awaited_once()
