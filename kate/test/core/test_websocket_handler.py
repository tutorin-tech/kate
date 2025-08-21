"""The module contains the unit tests for the WebSocketHandler class."""

import unittest
import zlib
from unittest.mock import AsyncMock, Mock, patch



from kate.core.escape import utf8, json_encode
from kate.core.websocket import WebSocketClosedError, WebSocketHandler
from kate.core.websocket import (
    _DecompressTooLargeError,
    _PerMessageDeflateCompressor as Compressor,
    _PerMessageDeflateDecompressor as Decompressor,
)


class _DummyServer:
    """Minimal server stub exposing send_http_error used by the protocol."""
    def __init__(self):
        self.send_http_error = AsyncMock()


def _make_writer():
    """Create a stream writer double."""
    w = Mock()
    w.write = Mock()
    w.drain = AsyncMock()
    w.close = Mock()
    w.wait_closed = AsyncMock()
    w.is_closing = Mock(return_value=False)
    return w


class TestWebSocketHandler(unittest.IsolatedAsyncioTestCase):
    """The class implements the tests for WebSocketHandler."""

    def setUp(self):
        """Prepare a fresh handler with a default, valid header set."""
        self.reader = AsyncMock()
        self.writer = _make_writer()
        self.server = _DummyServer()
        self.headers = {
            "Host": "example.com",
            "Origin": "http://example.com",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
        }
        self.handler = WebSocketHandler(self.headers, self.reader, self.writer, self.server)

    async def test_get_rejects_when_upgrade_header_is_not_websocket(self):
        """The handler should have the possibility to reject the request when
        the Upgrade header is not 'websocket'.
        """
        headers = dict(self.headers, Upgrade="h2c")
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        await handler.get()
        self.server.send_http_error.assert_awaited_once()
        args, _ = self.server.send_http_error.await_args
        self.assertEqual(args[0], self.writer)
        self.assertEqual(args[1], 400)
        self.assertIn("Upgrade", args[2])

    async def test_get_rejects_when_connection_header_does_not_include_upgrade(self):
        """The handler should have the possibility to reject the request when
        the Connection header does not contain 'upgrade'.
        """
        headers = dict(self.headers, Connection="keep-alive")
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        await handler.get()
        self.server.send_http_error.assert_awaited_once()
        args, _ = self.server.send_http_error.await_args
        self.assertEqual(args[1], 400)
        self.assertEqual('"Connection" must be "Upgrade".', args[2])

    async def test_get_allows_connection_header_with_comma_separated_upgrade(self):
        """The handler should have the possibility to accept the request when
        'upgrade' appears in a comma separated Connection list.
        """
        headers = dict(self.headers, Connection="keep-alive, Upgrade")
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        protocol = AsyncMock()
        with patch.object(handler, "get_websocket_protocol", return_value=protocol):
            await handler.get()
            protocol.accept_connection.assert_awaited_once_with(handler)
            self.server.send_http_error.assert_not_called()

    async def test_get_accepts_with_upgrade_header_any_case(self):
        """The handler should have the possibility to accept the request when
        the Upgrade header uses a different case.
        """
        headers = dict(self.headers, Upgrade="WebSocket")
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        protocol = AsyncMock()
        with patch.object(handler, "get_websocket_protocol", return_value=protocol):
            await handler.get()
            protocol.accept_connection.assert_awaited_once_with(handler)

    async def test_get_rejects_when_origin_is_invalid(self):
        """The handler should have the possibility to reject the request when
        the Origin does not match the Host.
        """
        headers = dict(self.headers, Origin="http://evil.com")
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        await handler.get()
        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 403, "Cross origin websockets not allowed"
        )

    async def test_get_uses_sec_websocket_origin_when_origin_is_missing(self):
        """The handler should have the possibility to validate the origin using
        'Sec-Websocket-Origin' when 'Origin' is not present.
        """
        headers = dict(self.headers)
        headers.pop("Origin", None)
        headers["Sec-Websocket-Origin"] = "http://example.com"
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        protocol = AsyncMock()
        with patch.object(handler, "get_websocket_protocol", return_value=protocol):
            await handler.get()
            protocol.accept_connection.assert_awaited_once_with(handler)

    async def test_get_allows_when_origin_header_is_missing(self):
        """The handler should have the possibility to accept the request when
        the Origin header is not present.
        """
        headers = dict(self.headers)
        headers.pop("Origin", None)
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        protocol = AsyncMock()
        with patch.object(handler, "get_websocket_protocol", return_value=protocol):
            await handler.get()
            protocol.accept_connection.assert_awaited_once_with(handler)

    async def test_get_returns_426_when_protocol_is_not_available(self):
        """The handler should have the possibility to return 426 Upgrade Required when
        no supported protocol is found.
        """
        with (
            patch.object(self.handler, "get_websocket_protocol", return_value=None),
            patch.object(self.server, "send_http_error", wraps=self.server.send_http_error) as spy
        ):
            await self.handler.get()
            spy.assert_awaited_once_with(self.writer, 426, "Upgrade Required")

    async def test_get_calls_accept_connection_on_success(self):
        """The handler should have the possibility to delegate handshake
        to the selected protocol.
        """
        protocol = AsyncMock()
        with patch.object(self.handler, "get_websocket_protocol", return_value=protocol):
            await self.handler.get()
            protocol.accept_connection.assert_awaited_once_with(self.handler)

    def test_ping_interval_property_reads_setting(self):
        """The handler should have the possibility to expose the configured ping interval."""
        self.assertIsNone(self.handler.ping_interval)
        self.handler.settings = {"websocket_ping_interval": 15}
        self.assertEqual(self.handler.ping_interval, 15)

    def test_ping_timeout_property_reads_setting(self):
        """The handler should have the possibility to expose the configured ping timeout."""
        self.assertIsNone(self.handler.ping_timeout)
        self.handler.settings = {"websocket_ping_timeout": 10}
        self.assertEqual(self.handler.ping_timeout, 10)

    def test_max_message_size_property_reads_setting_and_default(self):
        """The handler should have the possibility to expose the maximum message
        size with a sensible default.
        """
        self.assertEqual(self.handler.max_message_size, 10 * 1024 * 1024)
        self.handler.settings = {"websocket_max_message_size": 12345}
        self.assertEqual(self.handler.max_message_size, 12345)

    async def test_write_message_sends_text(self):
        """The handler should have the possibility to send a text message via the protocol."""
        conn = AsyncMock()
        conn.is_closing = Mock(return_value=False)
        self.handler.ws_connection = conn

        await self.handler.write_message("hello")
        conn.write_message.assert_awaited_once_with("hello", binary=False)

    async def test_write_message_sends_dict_as_json(self):
        """The handler should have the possibility to serialize dictionaries to
        JSON before sending.
        """
        conn = AsyncMock()
        conn.is_closing = Mock(return_value=False)
        self.handler.ws_connection = conn

        data = {"a": 1, "b": "</tag>"}
        await self.handler.write_message(data)

        sent = conn.write_message.await_args.args[0]
        self.assertEqual(sent, json_encode(data))
        self.assertIsInstance(sent, str)

    async def test_write_message_sends_binary_when_flag_true(self):
        """The handler should have the possibility to send binary data when
        the 'binary' flag is true.
        """
        conn = AsyncMock()
        conn.is_closing = Mock(return_value=False)
        self.handler.ws_connection = conn

        await self.handler.write_message(b"\x00\x01", binary=True)
        conn.write_message.assert_awaited_once_with(b"\x00\x01", binary=True)

    async def test_write_message_raises_when_connection_is_closed(self):
        """The handler should raise WebSocketClosedError when trying to
        send a message on a closed connection.
        """
        with self.assertRaises(WebSocketClosedError):
            await self.handler.write_message("hi")

        conn = AsyncMock()
        conn.is_closing.return_value = True
        self.handler.ws_connection = conn
        with self.assertRaises(WebSocketClosedError):
            await self.handler.write_message("hi")

    async def test_ping_sends_utf8_bytes_and_raises_when_closed(self):
        """The handler should have the possibility to send a ping as UTF-8 bytes and
        raise when closed.
        """
        conn = AsyncMock()
        conn.is_closing = Mock(return_value=False)
        self.handler.ws_connection = conn

        await self.handler.ping("привет")
        conn.write_ping.assert_awaited_once_with(utf8("привет"))

        self.handler.ws_connection = None
        with self.assertRaises(WebSocketClosedError):
            await self.handler.ping(b"x")

    async def test_close_proxies_to_connection_and_clears_reference(self):
        """The handler should have the possibility to close the connection and
        clear the internal reference.
        """
        conn = AsyncMock()
        self.handler.ws_connection = conn

        await self.handler.close(1000, "ok")
        conn.close.assert_awaited_once_with(1000, "ok")
        self.assertIsNone(self.handler.ws_connection)

    async def test_on_connection_close_calls_connection_once_and_on_close_once(self):
        """The handler should have the possibility to call on_connection_close and
        on_close only once and clear the connection.
        """
        conn = AsyncMock()
        self.handler.ws_connection = conn
        self.handler.on_close = AsyncMock()

        await self.handler.on_connection_close()
        conn.on_connection_close.assert_awaited_once()
        self.handler.on_close.assert_awaited_once()
        self.assertIsNone(self.handler.ws_connection)

        await self.handler.on_connection_close()
        self.handler.on_close.assert_awaited_once()

    async def test_on_ws_connection_close_sets_code_and_reason_and_delegates(self):
        """The handler should have the possibility to record the close code and reason
         and delegate to on_connection_close.
         """
        self.handler.on_connection_close = AsyncMock()
        await self.handler.on_ws_connection_close(1001, "bye")
        self.assertEqual(self.handler.close_code, 1001)
        self.assertEqual(self.handler.close_reason, "bye")
        self.handler.on_connection_close.assert_awaited_once()

    def test_select_subprotocol_returns_none_by_default(self):
        """The handler should have the possibility to return None when
        no subprotocol is selected by default.
        """
        self.assertIsNone(self.handler.select_subprotocol(["a", "b"]))

    def test_selected_subprotocol_reads_from_ws_connection(self):
        """The handler should have the possibility to expose the selected subprotocol
        from the underlying connection.
        """
        conn = Mock()
        conn.selected_subprotocol = "protocol"
        self.handler.ws_connection = conn
        self.assertEqual(self.handler.selected_subprotocol, "protocol")

    def test_selected_subprotocol_asserts_when_no_connection(self):
        """The handler should assert when accessing the selected subprotocol
        without an active connection.
        """
        self.handler.ws_connection = None
        with self.assertRaises(AssertionError):
            _ = self.handler.selected_subprotocol

    def test_get_compression_options_is_none_by_default(self):
        """The handler should have the possibility to disable compression by default."""
        self.assertIsNone(self.handler.get_compression_options())

    def test_check_origin_accepts_matching_host_including_port(self):
        """The handler should have the possibility to accept an Origin
        that matches Host (including port).
        """
        headers = dict(self.headers)
        headers["Host"] = "example.com:8888"
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        self.assertTrue(handler.check_origin("http://example.com:8888"))

    def test_check_origin_rejects_non_matching_host(self):
        """The handler should have the possibility to reject an Origin that does not match Host."""
        self.assertFalse(self.handler.check_origin("http://evil.com"))
        self.assertFalse(self.handler.check_origin("http://example.com:9999"))

    def test_set_nodelay_delegates_to_ws_connection(self):
        """The handler should have the possibility to enable TCP_NODELAY on the connection."""
        conn = Mock()
        self.handler.ws_connection = conn
        self.handler.set_nodelay(True)

        conn.set_nodelay.assert_called_once_with(True)

    def test_set_nodelay_asserts_without_connection(self):
        """The handler should assert when attempting to set TCP_NODELAY without
        an active connection.
        """
        self.handler.ws_connection = None
        with self.assertRaises(AssertionError):
            self.handler.set_nodelay(True)

    @patch("kate.core.websocket.WebSocketProtocol13")
    def test_get_websocket_protocol_returns_protocol_for_supported_versions(self, mock_proto_cls):
        """The handler should have the possibility to construct a protocol for
        supported versions and pass through settings.
        """
        mock_instance = Mock()
        mock_proto_cls.return_value = mock_instance

        self.handler.settings = {
            "ping_interval": 1.5,
            "ping_timeout": 5.0,
            "max_message_size": 12345,
        }
        self.handler.get_compression_options = Mock(return_value={"compression_level": 1})

        for ver in ("7", "8", "13"):
            headers = dict(self.headers, **{"Sec-WebSocket-Version": ver})
            handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
            handler.settings = self.handler.settings
            handler.get_compression_options = self.handler.get_compression_options
            result = handler.get_websocket_protocol()
            self.assertIs(result, mock_instance)
            mock_proto_cls.assert_called_with(
                handler, False, unittest.mock.ANY, self.reader, self.writer,
            )
            params = mock_proto_cls.call_args.args[2]
            self.assertEqual(params.ping_interval, 1.5)
            self.assertEqual(params.ping_timeout, 5.0)
            self.assertEqual(params.max_message_size, 12345)
            self.assertEqual(params.compression_options, {"compression_level": 1})

    def test_get_websocket_protocol_returns_none_for_unsupported_version(self):
        """The handler should have the possibility to return None when the
        WebSocket version is unsupported.
        """
        headers = dict(self.headers, **{"Sec-WebSocket-Version": "99"})
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        self.assertIsNone(handler.get_websocket_protocol())

    async def test_open_returns_none_by_default_and_on_message_must_be_overridden(self):
        """The handler should have the possibility to no-op in 'open' and require
        'on_message' to be overridden.
        """
        self.assertIsNone(await self.handler.open())
        with self.assertRaises(NotImplementedError):
            await self.handler.on_message("test message")


class TestPerMessageDeflateCompressor(unittest.TestCase):
    """The class implements the tests for the permessage-deflate compressor."""

    def test_constructor_rejects_invalid_max_wbits(self):
        """The compressor should have the possibility to reject max_wbits 
        outside of the allowed range.
        """
        with self.assertRaises(ValueError):
            Compressor(persistent=True, max_wbits=7)
        with self.assertRaises(ValueError):
            Compressor(persistent=True, max_wbits=zlib.MAX_WBITS + 1)

    def test_constructor_accepts_valid_max_wbits_and_sets_persistent_mode(self):
        """The compressor should have the possibility to accept a valid max_wbits and 
        configure persistent mode.
        """
        c1 = Compressor(persistent=True, max_wbits=9)
        self.assertIsNotNone(c1._compressor)

        c2 = Compressor(
            persistent=False,
            max_wbits=None,
            compression_options={
                "compression_level": 6,
                "mem_level": 8,
            })
        self.assertIsNone(c2._compressor)

    def test_compress_trims_zlib_sync_flush_tail(self):
        """The compressor should have the possibility to trim the zlib sync-flush 
        0x00 0x00 0xff 0xff trailer.
        """
        c = Compressor(persistent=True, max_wbits=15)
        out = c.compress(b"hello world")
        self.assertIsInstance(out, bytes)
        self.assertFalse(out.endswith(b"\x00\x00\xff\xff"))

    def test_compress_is_able_to_handle_binary_payload(self):
        """The compressor should have the possibility to compress arbitrary binary payloads."""
        payload = bytes(range(256)) * 4
        c = Compressor(persistent=False, max_wbits=15)
        out = c.compress(payload)
        self.assertGreater(len(out), 0)



class TestPerMessageDeflateDecompressor(unittest.TestCase):
    """The class implements the tests for the permessage-deflate decompressor."""

    def test_constructor_rejects_invalid_max_wbits(self):
        """The decompressor should have the possibility to reject max_wbits 
        outside of the allowed range.
        """
        with self.assertRaises(ValueError):
            Decompressor(persistent=True, max_wbits=7, max_message_size=1024)
        with self.assertRaises(ValueError):
            Decompressor(persistent=True, max_wbits=zlib.MAX_WBITS + 1, max_message_size=1024)

    def test_roundtrip_compress_then_decompress_persistent(self):
        """The compressor and decompressor should have the possibility to roundtrip 
        the payload in persistent mode.
        """
        payload = ("привет WebSocket " * 50).encode("utf-8")
        compressor = Compressor(persistent=True, max_wbits=15)
        decompressor = Decompressor(persistent=True, max_wbits=15, max_message_size=10_000_000)

        compressed = compressor.compress(payload)
        restored = decompressor.decompress(compressed)
        self.assertEqual(restored, payload)

    def test_roundtrip_compress_then_decompress_nonpersistent(self):
        """The compressor and decompressor should have the possibility to roundtrip 
        the payload in non-persistent mode.
        """
        payload = bytes(range(64)) * 100
        compressor = Compressor(persistent=False, max_wbits=15)
        decompressor = Decompressor(persistent=False, max_wbits=None, max_message_size=10_000_000)

        compressed = compressor.compress(payload)
        restored = decompressor.decompress(compressed)
        self.assertEqual(restored, payload)

    def test_decompress_raises_when_result_exceeds_max_message_size(self):
        """The decompressor should have the possibility to raise when the uncompressed 
        result exceeds the configured max_message_size.
        """
        payload = b"a" * 10_000
        compressor = Compressor(persistent=False, max_wbits=15)
        compressed = compressor.compress(payload)

        tiny = Decompressor(persistent=False, max_wbits=15, max_message_size=1024)
        with self.assertRaises(_DecompressTooLargeError):
            _ = tiny.decompress(compressed)

    def test_multiple_calls_do_not_leave_unconsumed_tail(self):
        """The decompressor should have the possibility to fully consume input without 
        leaving unconsumed tail.
        """
        payload1 = b"alpha" * 200
        payload2 = b"beta" * 300

        compressor = Compressor(persistent=True, max_wbits=15)
        decompressor = Decompressor(persistent=True, max_wbits=15, max_message_size=10_000_000)

        c1 = compressor.compress(payload1)
        r1 = decompressor.decompress(c1)
        self.assertEqual(r1, payload1)

        c2 = compressor.compress(payload2)
        r2 = decompressor.decompress(c2)
        self.assertEqual(r2, payload2)

    def test_nonpersistent_decompressor_creates_new_instance_per_call(self):
        """The decompressor should have the possibility to create a new internal zlib 
        object on each call when non-persistent.
        """
        decompressor = Decompressor(persistent=False, max_wbits=15, max_message_size=10_000_000)
        self.assertIsNone(decompressor._decompressor)
        compressor = Compressor(persistent=False, max_wbits=15)
        _ = decompressor.decompress(compressor.compress(b"sample"))
        self.assertIsNone(decompressor._decompressor)


class TestPerMessageDeflateDefaults(unittest.TestCase):
    """The class implements the tests for default compression options."""

    def test_default_compression_level_is_taken_from_tornado_constant(self):
        """The compressor should have the possibility to use Tornado's default 
        compression level when options are not provided.
        """
        compressor = Compressor(persistent=True, max_wbits=15)
        out = compressor.compress(b"x" * 1000)
        self.assertIsInstance(out, bytes)
        self.assertGreater(len(out), 0)
