"""The module contains the unit tests for the WebSocketHandler class."""

# ruff: noqa: FBT003

import unittest
from unittest.mock import AsyncMock, Mock, patch

from kate.core.escape import json_encode, utf8
from kate.core.websocket import WebSocketClosedError, WebSocketHandler
from kate.test.core.base import BaseWebSocketTestCase


class TestWebSocketHandler(BaseWebSocketTestCase):  # noqa: PLR0904
    """The class implements the tests for WebSocketHandler."""

    def test_check_origin_accepts_matching_host_including_port(self):
        """The handler should have the possibility to accept an Origin
        that matches Host (including port).
        """
        headers = dict(self.headers)
        headers['Host'] = 'example.com:8888'
        handler_with_port = WebSocketHandler(headers, self.reader, self.writer, self.server)

        self.assertTrue(handler_with_port.check_origin('http://example.com:8888'))

    def test_check_origin_rejects_non_matching_host(self):
        """The handler should have the possibility to reject an Origin that does not match Host."""
        self.assertFalse(self.handler.check_origin('http://evil.com'))
        self.assertFalse(self.handler.check_origin('http://example.com:9999'))

    async def test_close_proxies_to_connection_and_clears_reference(self):
        """The handler should have the possibility to close the connection and
        clear the internal reference.
        """
        mock_connection = AsyncMock()
        self.handler.ws_connection = mock_connection

        await self.handler.close(1000, 'ok')
        mock_connection.close.assert_awaited_once_with(1000, 'ok')
        self.assertIsNone(self.handler.ws_connection)

    async def test_get_accepts_with_upgrade_header_any_case(self):
        """The handler should have the possibility to accept the request when
        the Upgrade header uses a different case.
        """
        headers = dict(self.headers, Upgrade='WebSocket')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        mock_protocol = AsyncMock()
        with patch.object(
            handler,
            'get_websocket_protocol',
            return_value=mock_protocol,
        ):
            await handler.get()

        mock_protocol.accept_connection.assert_awaited_once_with(handler)

    async def test_get_allows_connection_header_with_comma_separated_upgrade(self):
        """The handler should have the possibility to accept the request when
        'upgrade' appears in a comma separated Connection list.
        """
        headers = dict(self.headers, Connection='keep-alive, Upgrade')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        mock_protocol = AsyncMock()
        with patch.object(
            handler,
            'get_websocket_protocol',
            return_value=mock_protocol,
        ):
            await handler.get()

        mock_protocol.accept_connection.assert_awaited_once_with(handler)
        self.server.send_http_error.assert_not_called()

    async def test_get_allows_when_origin_header_is_missing(self):
        """The handler should have the possibility to accept the request when
        the Origin header is not present.
        """
        headers = dict(self.headers)
        headers.pop('Origin', None)
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        mock_protocol = AsyncMock()
        with patch.object(handler, 'get_websocket_protocol', return_value=mock_protocol):
            await handler.get()

        mock_protocol.accept_connection.assert_awaited_once_with(handler)

    async def test_get_calls_accept_connection_on_success(self):
        """The handler should have the possibility to delegate handshake
        to the selected protocol.
        """
        protocol_mock = AsyncMock()
        with patch.object(
            self.handler,
            'get_websocket_protocol',
            return_value=protocol_mock,
        ):
            await self.handler.get()

        protocol_mock.accept_connection.assert_awaited_once_with(self.handler)

    def test_get_compression_options_is_none_by_default(self):
        """The handler should have the possibility to disable compression by default."""
        self.assertIsNone(self.handler.get_compression_options())

    async def test_get_rejects_when_connection_header_does_not_include_upgrade(self):
        """The handler should have the possibility to reject the request when
        the Connection header does not contain 'upgrade'.
        """
        headers = dict(self.headers, Connection='keep-alive')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 400, '"Connection" must be "Upgrade".',
        )

    async def test_get_rejects_when_origin_is_invalid(self):
        """The handler should have the possibility to reject the request when
        the Origin does not match the Host.
        """
        headers = dict(self.headers, Origin='http://evil.com')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 403, 'Cross origin websockets not allowed',
        )

    async def test_get_rejects_when_upgrade_header_is_not_websocket(self):
        """The handler should have the possibility to reject the request when
        the Upgrade header is not 'websocket'.
        """
        headers = dict(self.headers, Upgrade='h2c')
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        await handler.get()

        self.server.send_http_error.assert_awaited_once_with(
            self.writer, 400, 'Can "Upgrade" only to "WebSocket".',
        )

    async def test_get_returns_426_when_protocol_is_not_available(self):
        """The handler should have the possibility to return 426 Upgrade Required when
        no supported protocol is found.
        """
        with (
            patch.object(self.handler, 'get_websocket_protocol', return_value=None),
            patch.object(
                self.server,
                'send_http_error',
                wraps=self.server.send_http_error,
            ) as send_http_error_mock,
        ):
            await self.handler.get()

        send_http_error_mock.assert_awaited_once_with(
            self.writer,
            code=426,
            message='Upgrade Required',
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'Sec-WebSocket-Version': '7, 8, 13',
            },
        )

    async def test_get_uses_sec_websocket_origin_when_origin_is_missing(self):
        """The handler should have the possibility to validate the origin using
        'Sec-Websocket-Origin' when 'Origin' is not present.
        """
        headers = dict(self.headers)
        headers.pop('Origin', None)
        headers['Sec-Websocket-Origin'] = 'http://example.com'
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)

        mock_protocol = AsyncMock()
        with patch.object(
            handler,
            'get_websocket_protocol',
            return_value=mock_protocol,
        ):
            await handler.get()

        mock_protocol.accept_connection.assert_awaited_once_with(handler)

    def test_get_websocket_protocol_returns_none_for_unsupported_version(self):
        """The handler should have the possibility to return None when the
        WebSocket version is unsupported.
        """
        headers = dict(self.headers, **{'Sec-WebSocket-Version': '99'})
        handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
        self.assertIsNone(handler.get_websocket_protocol())

    def test_get_websocket_protocol_returns_protocol_for_supported_versions(self):
        """The handler should have the possibility to construct a protocol for
        supported versions and pass through settings.
        """
        protocol_instance = Mock()
        with patch(
            'kate.core.websocket.WebSocketProtocol13',
            return_value=protocol_instance,
        ) as mock_protocol_class:
            supported_versions = ('7', '8', '13')
            for websocket_version in supported_versions:
                headers = dict(self.headers, **{'Sec-WebSocket-Version': websocket_version})
                handler = WebSocketHandler(headers, self.reader, self.writer, self.server)
                handler.settings = {
                    'ping_interval': 1.5,
                    'ping_timeout': 5.0,
                    'max_message_size': 12345,
                }
                handler.get_compression_options = Mock(
                    return_value={'compression_level': 1},
                )

                protocol_returned = handler.get_websocket_protocol()

                self.assertIs(protocol_returned, protocol_instance)
                mock_protocol_class.assert_called_with(
                    handler,
                    False,
                    unittest.mock.ANY,
                    self.reader,
                    self.writer,
                )
                protocol_params = mock_protocol_class.call_args.args[2]
                self.assertEqual(protocol_params.ping_interval, 1.5)
                self.assertEqual(protocol_params.ping_timeout, 5.0)
                self.assertEqual(protocol_params.max_message_size, 12345)
                self.assertEqual(protocol_params.compression_options, {'compression_level': 1})

    def test_max_message_size_property_reads_setting_and_default(self):
        """The handler should have the possibility to expose the maximum message
        size with a sensible default.
        """
        self.assertEqual(self.handler.max_message_size, 10 * 1024 * 1024)
        self.handler.settings = {'websocket_max_message_size': 12345}
        self.assertEqual(self.handler.max_message_size, 12345)

    async def test_on_connection_close_calls_connection_once_and_on_close_once(self):
        """The handler should have the possibility to call on_connection_close and
        on_close only once and clear the connection.
        """
        mock_connection = AsyncMock()
        self.handler.ws_connection = mock_connection
        self.handler.on_close = AsyncMock()

        await self.handler.on_connection_close()

        mock_connection.on_connection_close.assert_awaited_once()
        self.handler.on_close.assert_awaited_once()
        self.assertIsNone(self.handler.ws_connection)

        await self.handler.on_connection_close()
        self.handler.on_close.assert_awaited_once()

    async def test_on_ws_connection_close_sets_code_and_reason_and_delegates(self):
        """The handler should have the possibility to record the close code and reason
        and delegate to on_connection_close.
        """
        self.handler.on_connection_close = AsyncMock()
        await self.handler.on_ws_connection_close(1001, 'bye')

        self.assertEqual(self.handler.close_code, 1001)
        self.assertEqual(self.handler.close_reason, 'bye')
        self.handler.on_connection_close.assert_awaited_once()

    async def test_open_returns_none_by_default_and_on_message_must_be_overridden(self):
        """The handler should have the possibility to no-op in 'open' and require
        'on_message' to be overridden.
        """
        self.assertIsNone(await self.handler.open())
        with self.assertRaises(NotImplementedError):
            await self.handler.on_message('test message')

    def test_ping_interval_property_reads_setting(self):
        """The handler should have the possibility to expose the configured ping interval."""
        self.assertIsNone(self.handler.ping_interval)
        self.handler.settings = {'websocket_ping_interval': 15}
        self.assertEqual(self.handler.ping_interval, 15)

    async def test_ping_sends_utf8_bytes_and_raises_when_closed(self):
        """The handler should have the possibility to send a ping as UTF-8 bytes and
        raise when closed.
        """
        mock_connection = AsyncMock()
        mock_connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = mock_connection

        await self.handler.ping('hello')
        mock_connection.write_ping.assert_awaited_once_with(utf8('hello'))

        self.handler.ws_connection = None
        with self.assertRaises(WebSocketClosedError):
            await self.handler.ping(b'hello again')

    def test_ping_timeout_property_reads_setting(self):
        """The handler should have the possibility to expose the configured ping timeout."""
        self.assertIsNone(self.handler.ping_timeout)
        self.handler.settings = {'websocket_ping_timeout': 10}
        self.assertEqual(self.handler.ping_timeout, 10)

    def test_select_subprotocol_returns_none_by_default(self):
        """The handler should have the possibility to return None when
        no subprotocol is selected by default.
        """
        self.assertIsNone(self.handler.select_subprotocol(['a', 'b']))

    def test_selected_subprotocol_asserts_when_no_connection(self):
        """The handler should assert when accessing the selected subprotocol
        without an active connection.
        """
        self.handler.ws_connection = None
        with self.assertRaises(AssertionError):
            _ = self.handler.selected_subprotocol

    def test_selected_subprotocol_reads_from_ws_connection(self):
        """The handler should have the possibility to expose the selected subprotocol
        from the underlying connection.
        """
        mock_underlying_connection = Mock()
        mock_underlying_connection.selected_subprotocol = 'protocol'
        self.handler.ws_connection = mock_underlying_connection

        self.assertEqual(self.handler.selected_subprotocol, 'protocol')

    def test_set_nodelay_asserts_without_connection(self):
        """The handler should assert when attempting to set TCP_NODELAY without
        an active connection.
        """
        self.handler.ws_connection = None
        with self.assertRaises(AssertionError):
            self.handler.set_nodelay(True)

    def test_set_nodelay_delegates_to_ws_connection(self):
        """The handler should have the possibility to enable TCP_NODELAY on the connection."""
        mock_connection = Mock()
        self.handler.ws_connection = mock_connection
        self.handler.set_nodelay(True)

        mock_connection.set_nodelay.assert_called_once_with(True)

    async def test_write_message_raises_when_connection_is_closed(self):
        """The handler should raise WebSocketClosedError when trying to
        send a message on a closed connection.
        """
        with self.assertRaises(WebSocketClosedError):
            await self.handler.write_message('hi')

        mock_connection = Mock()
        mock_connection.is_closing.return_value = True
        self.handler.ws_connection = mock_connection

        with self.assertRaises(WebSocketClosedError):
            await self.handler.write_message('hi')

    async def test_write_message_sends_binary_when_flag_true(self):
        """The handler should have the possibility to send binary data when
        the 'binary' flag is true.
        """
        mock_connection = AsyncMock()
        mock_connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = mock_connection

        await self.handler.write_message(b'\x00\x01', binary=True)
        mock_connection.write_message.assert_awaited_once_with(b'\x00\x01', binary=True)

    async def test_write_message_sends_dict_as_json(self):
        """The handler should have the possibility to serialize dictionaries to
        JSON before sending.
        """
        mock_connection = AsyncMock()
        mock_connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = mock_connection

        data = {'1': 1, '2': '2'}
        await self.handler.write_message(data)

        sent_value = mock_connection.write_message.await_args.args[0]
        self.assertEqual(sent_value, json_encode(data))
        self.assertIsInstance(sent_value, str)

    async def test_write_message_sends_text(self):
        """The handler should have the possibility to send a text message via the protocol."""
        mock_connection = AsyncMock()
        mock_connection.is_closing = Mock(return_value=False)
        self.handler.ws_connection = mock_connection

        await self.handler.write_message('hello')
        mock_connection.write_message.assert_awaited_once_with('hello', binary=False)
