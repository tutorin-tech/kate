#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""``tornado.web`` provides a simple web framework with asynchronous
features that allow it to scale to large numbers of open connections,
making it ideal for `long polling
<http://en.wikipedia.org/wiki/Push_technology#Long_polling>`_.

Here is a simple "Hello, world" example app:

.. testcode::

    import asyncio
    import tornado

    class MainHandler(tornado.web.RequestHandler):
        def get(self):
            self.write("Hello, world")

    async def main():
        application = tornado.web.Application([
            (r"/", MainHandler),
        ])
        application.listen(8888)
        await asyncio.Event().wait()

    if __name__ == "__main__":
        asyncio.run(main())

See the :doc:`guide` for additional information.

Thread-safety notes
-------------------

In general, methods on `RequestHandler` and elsewhere in Tornado are
not thread-safe. In particular, methods such as
`~RequestHandler.write()`, `~RequestHandler.finish()`, and
`~RequestHandler.flush()` must only be called from the main thread. If
you use multiple threads it is important to use `.IOLoop.add_callback`
to transfer control back to the main thread before finishing the
request, or to limit your use of other threads to
`.IOLoop.run_in_executor` and ensure that your callbacks running in
the executor do not refer to Tornado objects.

"""

import datetime
import email.utils
import hashlib
from inspect import isclass
import logging
import mimetypes
import numbers
import os.path
import re
import sys
import threading
import time

from kate.server.concurrent import Future, future_set_result_unless_cancelled
from kate.server import escape, gen, httputil, iostream
from kate.server.escape import utf8, _unicode
from kate.server.routing import (
    AnyMatches,
    ReversibleRouter,
    Rule,
    ReversibleRuleRouter,
    _RuleList,
)
from kate.server.util import unicode_type

from typing import (
    Dict,
    Any,
    Union,
    Optional,
    Awaitable,
    Tuple,
    List,
    Callable,
    Generator,
    Type,
    TypeVar,
    cast,
)
import typing

if typing.TYPE_CHECKING:
    from typing import Set  # noqa: F401

LOGGER = logging.getLogger(__name__)


# The following types are accepted by RequestHandler.set_header
# and related methods.
_HeaderTypes = Union[bytes, unicode_type, int, numbers.Integral, datetime.datetime]


class RequestHandler:
    """Base class for HTTP request handlers.

    Subclasses must define at least one of the methods defined in the
    "Entry points" section below.

    Applications should not construct `RequestHandler` objects
    directly and subclasses should not override ``__init__`` (override
    `~RequestHandler.initialize` instead).

    """

    SUPPORTED_METHODS: Tuple[str, ...] = (
        "GET",
        "HEAD",
        "POST",
        "DELETE",
        "PATCH",
        "PUT",
        "OPTIONS",
    )

    _remove_control_chars_regex = re.compile(r"[\x00-\x08\x0e-\x1f]")

    # Will be set in _execute.
    path_args = None  # type: List[str]
    path_kwargs = None  # type: Dict[str, str]

    def __init__(
        self,
        application: "Application",
        request: httputil.HTTPServerRequest,
        **kwargs: Any,
    ) -> None:
        super().__init__()

        self.application = application
        self.request = request
        self._headers_written = False
        self._finished = False
        self._auto_finish = True
        self._prepared_future = None
        self.clear()
        assert self.request.connection is not None
        # TODO: need to add set_close_callback to HTTPConnection interface
        self.request.connection.set_close_callback(  # type: ignore
            self.on_connection_close
        )
        self.initialize(**kwargs)  # type: ignore

    def _initialize(self) -> None:
        pass

    initialize = _initialize  # type: Callable[..., None]

    @property
    def settings(self) -> Dict[str, Any]:
        """An alias for `self.application.settings <Application.settings>`."""
        return self.application.settings

    def _unimplemented_method(self, *args: str, **kwargs: str) -> None:
        raise HTTPError(405)

    head = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]
    get = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]
    post = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]
    delete = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]
    patch = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]
    put = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]
    options = _unimplemented_method  # type: Callable[..., Optional[Awaitable[None]]]

    def on_connection_close(self) -> None:
        """Called in async handlers if the client closed the connection.

        Override this to clean up resources associated with
        long-lived connections.  Note that this method is called only if
        the connection was closed during asynchronous processing; if you
        need to do cleanup after every request override `on_finish`
        instead.

        Proxies may keep a connection open for a time (perhaps
        indefinitely) after the client has gone away, so this method
        may not be called promptly after the end user closes their
        connection.
        """
        pass

    def clear(self) -> None:
        """Resets all headers and content for this response."""
        self._headers = httputil.HTTPHeaders(
            {
                "Server": "TornadoServer/%s" % 'tornado.version',
                "Content-Type": "text/html; charset=UTF-8",
                "Date": httputil.format_timestamp(time.time()),
            }
        )
        self.set_default_headers()
        self._write_buffer = []  # type: List[bytes]
        self._status_code = 200
        self._reason = httputil.responses[200]

    def set_default_headers(self) -> None:
        """Override this to set HTTP headers at the beginning of the request.

        For example, this is the place to set a custom ``Server`` header.
        Note that setting such headers in the normal flow of request
        processing may not do what you want, since headers may be reset
        during error handling.
        """
        pass

    def set_status(self, status_code: int, reason: Optional[str] = None) -> None:
        """Sets the status code for our response.

        :arg int status_code: Response status code.
        :arg str reason: Human-readable reason phrase describing the status
            code. If ``None``, it will be filled in from
            `http.client.responses` or "Unknown".

        .. versionchanged:: 5.0

           No longer validates that the response code is in
           `http.client.responses`.
        """
        self._status_code = status_code
        if reason is not None:
            self._reason = escape.native_str(reason)
        else:
            self._reason = httputil.responses.get(status_code, "Unknown")

    def get_status(self) -> int:
        """Returns the status code for our response."""
        return self._status_code

    def set_header(self, name: str, value: _HeaderTypes) -> None:
        """Sets the given response header name and value.

        All header values are converted to strings (`datetime` objects
        are formatted according to the HTTP specification for the
        ``Date`` header).

        """
        self._headers[name] = self._convert_header_value(value)

    def clear_header(self, name: str) -> None:
        """Clears an outgoing header, undoing a previous `set_header` call.

        Note that this method does not apply to multi-valued headers
        set by `add_header`.
        """
        if name in self._headers:
            del self._headers[name]

    # https://www.rfc-editor.org/rfc/rfc9110#name-field-values
    _VALID_HEADER_CHARS = re.compile(r"[\x09\x20-\x7e\x80-\xff]*")

    def _convert_header_value(self, value: _HeaderTypes) -> str:
        # Convert the input value to a str. This type check is a bit
        # subtle: The bytes case only executes on python 3, and the
        # unicode case only executes on python 2, because the other
        # cases are covered by the first match for str.
        if isinstance(value, str):
            retval = value
        elif isinstance(value, bytes):
            # Non-ascii characters in headers are not well supported,
            # but if you pass bytes, use latin1 so they pass through as-is.
            retval = value.decode("latin1")
        elif isinstance(value, numbers.Integral):
            # return immediately since we know the converted value will be safe
            return str(value)
        elif isinstance(value, datetime.datetime):
            return httputil.format_timestamp(value)
        else:
            raise TypeError("Unsupported header value %r" % value)
        # If \n is allowed into the header, it is possible to inject
        # additional headers or split the request.
        if RequestHandler._VALID_HEADER_CHARS.fullmatch(retval) is None:
            raise ValueError("Unsafe header value %r", retval)
        return retval

    def decode_argument(self, value: bytes, name: Optional[str] = None) -> str:
        """Decodes an argument from the request.

        The argument has been percent-decoded and is now a byte string.
        By default, this method decodes the argument as utf-8 and returns
        a unicode string, but this may be overridden in subclasses.

        This method is used as a filter for both `get_argument()` and for
        values extracted from the url and passed to `get()`/`post()`/etc.

        The name of the argument is provided if known, but may be None
        (e.g. for unnamed groups in the url regex).
        """
        try:
            return _unicode(value)
        except UnicodeDecodeError:
            raise HTTPError(
                400, "Invalid unicode in {}: {!r}".format(name or "url", value[:40])
            )

    def write(self, chunk: Union[str, bytes, dict]) -> None:
        """Writes the given chunk to the output buffer.

        To write the output to the network, use the `flush()` method below.

        If the given chunk is a dictionary, we write it as JSON and set
        the Content-Type of the response to be ``application/json``.
        (if you want to send JSON as a different ``Content-Type``, call
        ``set_header`` *after* calling ``write()``).

        Note that lists are not converted to JSON because of a potential
        cross-site security vulnerability.  All JSON output should be
        wrapped in a dictionary.  More details at
        http://haacked.com/archive/2009/06/25/json-hijacking.aspx/ and
        https://github.com/facebook/tornado/issues/1009
        """
        if self._finished:
            raise RuntimeError("Cannot write() after finish()")
        if not isinstance(chunk, (bytes, unicode_type, dict)):
            message = "write() only accepts bytes, unicode, and dict objects"
            if isinstance(chunk, list):
                message += (
                    ". Lists not accepted for security reasons; see "
                    + "http://www.tornadoweb.org/en/stable/web.html#tornado.web.RequestHandler.write"  # noqa: E501
                )
            raise TypeError(message)
        if isinstance(chunk, dict):
            chunk = escape.json_encode(chunk)
            self.set_header("Content-Type", "application/json; charset=UTF-8")
        chunk = utf8(chunk)
        self._write_buffer.append(chunk)

    def flush(self, include_footers: bool = False) -> "Future[None]":
        """Flushes the current output buffer to the network.

        .. versionchanged:: 4.0
           Now returns a `.Future` if no callback is given.

        .. versionchanged:: 6.0

           The ``callback`` argument was removed.
        """
        assert self.request.connection is not None
        chunk = b"".join(self._write_buffer)
        self._write_buffer = []
        if not self._headers_written:
            self._headers_written = True
            # Ignore the chunk and only write the headers for HEAD requests
            if self.request.method == "HEAD":
                chunk = b""

            start_line = httputil.ResponseStartLine("", self._status_code, self._reason)
            return self.request.connection.write_headers(
                start_line, self._headers, chunk
            )
        else:
            # Ignore the chunk and only write the headers for HEAD requests
            if self.request.method != "HEAD":
                return self.request.connection.write(chunk)
            else:
                future = Future()  # type: Future[None]
                future.set_result(None)
                return future

    def finish(self, chunk: Optional[Union[str, bytes, dict]] = None) -> "Future[None]":
        """Finishes this response, ending the HTTP request.

        Passing a ``chunk`` to ``finish()`` is equivalent to passing that
        chunk to ``write()`` and then calling ``finish()`` with no arguments.

        Returns a `.Future` which may optionally be awaited to track the sending
        of the response to the client. This `.Future` resolves when all the response
        data has been sent, and raises an error if the connection is closed before all
        data can be sent.

        .. versionchanged:: 5.1

           Now returns a `.Future` instead of ``None``.
        """
        if self._finished:
            raise RuntimeError("finish() called twice")

        if chunk is not None:
            self.write(chunk)

        # Automatically support ETags and add the Content-Length header if
        # we have not flushed any content yet.
        if not self._headers_written:
            if (
                self._status_code == 200
                and self.request.method in ("GET", "HEAD")
                and "Etag" not in self._headers
            ):
                self.set_etag_header()
                if self.check_etag_header():
                    self._write_buffer = []
                    self.set_status(304)
            if self._status_code in (204, 304) or (100 <= self._status_code < 200):
                assert not self._write_buffer, (
                    "Cannot send body with %s" % self._status_code
                )
                self._clear_representation_headers()
            elif "Content-Length" not in self._headers:
                content_length = sum(len(part) for part in self._write_buffer)
                self.set_header("Content-Length", content_length)

        assert self.request.connection is not None
        # Now that the request is finished, clear the callback we
        # set on the HTTPConnection (which would otherwise prevent the
        # garbage collection of the RequestHandler when there
        # are keepalive connections)
        self.request.connection.set_close_callback(None)  # type: ignore

        future = self.flush(include_footers=True)
        self.request.connection.finish()
        self._log()
        self._finished = True
        return future

    def detach(self) -> iostream.IOStream:
        """Take control of the underlying stream.

        Returns the underlying `.IOStream` object and stops all
        further HTTP processing. Intended for implementing protocols
        like websockets that tunnel over an HTTP handshake.

        This method is only supported when HTTP/1.1 is used.

        .. versionadded:: 5.1
        """
        self._finished = True
        # TODO: add detach to HTTPConnection?
        return self.request.connection.detach()  # type: ignore

    def send_error(self, status_code: int = 500, **kwargs: Any) -> None:
        """Sends the given HTTP error code to the browser.

        If `flush()` has already been called, it is not possible to send
        an error, so this method will simply terminate the response.
        If output has been written but not yet flushed, it will be discarded
        and replaced with the error page.

        Override `write_error()` to customize the error page that is returned.
        Additional keyword arguments are passed through to `write_error`.
        """
        if self._headers_written:
            LOGGER.error("Cannot send error response after headers written")
            if not self._finished:
                # If we get an error between writing headers and finishing,
                # we are unlikely to be able to finish due to a
                # Content-Length mismatch. Try anyway to release the
                # socket.
                try:
                    self.finish()
                except Exception:
                    LOGGER.error("Failed to flush partial response", exc_info=True)
            return
        self.clear()

        reason = kwargs.get("reason")
        if "exc_info" in kwargs:
            exception = kwargs["exc_info"][1]
            if isinstance(exception, HTTPError) and exception.reason:
                reason = exception.reason
        self.set_status(status_code, reason=reason)
        try:
            self.write_error(status_code, **kwargs)
        except Exception:
            LOGGER.error("Uncaught exception in write_error", exc_info=True)
        if not self._finished:
            self.finish()

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        """Override to implement custom error pages.

        ``write_error`` may call `write`, `render`, `set_header`, etc
        to produce output as usual.

        If this error was caused by an uncaught exception (including
        HTTPError), an ``exc_info`` triple will be available as
        ``kwargs["exc_info"]``.  Note that this exception may not be
        the "current" exception for purposes of methods like
        ``sys.exc_info()`` or ``traceback.format_exc``.
        """
        self.finish(
            "<html><title>%(code)d: %(message)s</title>"
            "<body>%(code)d: %(message)s</body></html>"
            % {"code": status_code, "message": self._reason}
        )

    def require_setting(self, name: str, feature: str = "this feature") -> None:
        """Raises an exception if the given app setting is not defined."""
        if not self.application.settings.get(name):
            raise Exception(
                "You must define the '%s' setting in your "
                "application to use %s" % (name, feature)
            )

    def compute_etag(self) -> Optional[str]:
        """Computes the etag header to be used for this request.

        By default uses a hash of the content written so far.

        May be overridden to provide custom etag implementations,
        or may return None to disable tornado's default etag support.
        """
        hasher = hashlib.sha1()
        for part in self._write_buffer:
            hasher.update(part)
        return '"%s"' % hasher.hexdigest()

    def set_etag_header(self) -> None:
        """Sets the response's Etag header using ``self.compute_etag()``.

        Note: no header will be set if ``compute_etag()`` returns ``None``.

        This method is called automatically when the request is finished.
        """
        etag = self.compute_etag()
        if etag is not None:
            self.set_header("Etag", etag)

    def check_etag_header(self) -> bool:
        """Checks the ``Etag`` header against requests's ``If-None-Match``.

        Returns ``True`` if the request's Etag matches and a 304 should be
        returned. For example::

            self.set_etag_header()
            if self.check_etag_header():
                self.set_status(304)
                return

        This method is called automatically when the request is finished,
        but may be called earlier for applications that override
        `compute_etag` and want to do an early check for ``If-None-Match``
        before completing the request.  The ``Etag`` header should be set
        (perhaps with `set_etag_header`) before calling this method.
        """
        computed_etag = utf8(self._headers.get("Etag", ""))
        # Find all weak and strong etag values from If-None-Match header
        # because RFC 7232 allows multiple etag values in a single header.
        etags = re.findall(
            rb'\*|(?:W/)?"[^"]*"', utf8(self.request.headers.get("If-None-Match", ""))
        )
        if not computed_etag or not etags:
            return False

        match = False
        if etags[0] == b"*":
            match = True
        else:
            # Use a weak comparison when comparing entity-tags.
            def val(x: bytes) -> bytes:
                return x[2:] if x.startswith(b"W/") else x

            for etag in etags:
                if val(etag) == val(computed_etag):
                    match = True
                    break
        return match

    async def _execute(self, *args: bytes, **kwargs: bytes) -> None:
        """Executes this request with the given output transforms."""
        try:
            if self.request.method not in self.SUPPORTED_METHODS:
                raise HTTPError(405)

            self.path_args = [self.decode_argument(arg) for arg in args]
            self.path_kwargs = {
                k: self.decode_argument(v, name=k) for (k, v) in kwargs.items()
            }

            if self._prepared_future is not None:
                # Tell the Application we've finished with prepare()
                # and are ready for the body to arrive.
                future_set_result_unless_cancelled(self._prepared_future, None)
            if self._finished:
                return

            method = getattr(self, self.request.method.lower())
            result = method(*self.path_args, **self.path_kwargs)
            if result is not None:
                result = await result
            if self._auto_finish and not self._finished:
                self.finish()
        except Exception as e:
            try:
                self._handle_request_exception(e)
            except Exception:
                LOGGER.error("Exception in exception handler", exc_info=True)
            finally:
                # Unset result to avoid circular references
                result = None
            if self._prepared_future is not None and not self._prepared_future.done():
                # In case we failed before setting _prepared_future, do it
                # now (to unblock the HTTP server).  Note that this is not
                # in a finally block to avoid GC issues prior to Python 3.4.
                self._prepared_future.set_result(None)

    def _log(self) -> None:
        """Logs the current request.

        Sort of deprecated since this functionality was moved to the
        Application, but left in place for the benefit of existing apps
        that have overridden this method.
        """
        self.application.log_request(self)

    def _request_summary(self) -> str:
        return "{} {} ({})".format(
            self.request.method,
            self.request.uri,
            self.request.remote_ip,
        )

    def _handle_request_exception(self, e: BaseException) -> None:
        if isinstance(e, Finish):
            # Not an error; just finish the request without logging.
            if not self._finished:
                self.finish(*e.args)
            return

        LOGGER.error("Error in exception logger", exc_info=True)

        if self._finished:
            # Extra errors after the request has been finished should
            # be logged, but there is no reason to continue to try and
            # send a response.
            return
        if isinstance(e, HTTPError):
            self.send_error(e.status_code, exc_info=sys.exc_info())
        else:
            self.send_error(500, exc_info=sys.exc_info())

    def _clear_representation_headers(self) -> None:
        # 304 responses should not contain representation metadata
        # headers (defined in
        # https://tools.ietf.org/html/rfc7231#section-3.1)
        # not explicitly allowed by
        # https://tools.ietf.org/html/rfc7232#section-4.1
        headers = ["Content-Encoding", "Content-Language", "Content-Type"]
        for h in headers:
            self.clear_header(h)


_RequestHandlerType = TypeVar("_RequestHandlerType", bound=RequestHandler)


class _ApplicationRouter(ReversibleRuleRouter):
    """Routing implementation used internally by `Application`.

    Provides a binding between `Application` and `RequestHandler`.
    This implementation extends `~.routing.ReversibleRuleRouter` in a couple of ways:
        * it allows to use `RequestHandler` subclasses as `~.routing.Rule` target and
        * it allows to use a list/tuple of rules as `~.routing.Rule` target.
        ``process_rule`` implementation will substitute this list with an appropriate
        `_ApplicationRouter` instance.
    """

    def __init__(
        self, application: "Application", rules: Optional[_RuleList] = None
    ) -> None:
        assert isinstance(application, Application)
        self.application = application
        super().__init__(rules)

    def process_rule(self, rule: Rule) -> Rule:
        rule = super().process_rule(rule)

        if isinstance(rule.target, (list, tuple)):
            rule.target = _ApplicationRouter(
                self.application, rule.target  # type: ignore
            )

        return rule

    def get_target_delegate(
        self, target: Any, request: httputil.HTTPServerRequest, **target_params: Any
    ) -> Optional[httputil.HTTPMessageDelegate]:
        if isclass(target) and issubclass(target, RequestHandler):
            return self.application.get_handler_delegate(
                request, target, **target_params
            )

        return super().get_target_delegate(target, request, **target_params)


class Application(ReversibleRouter):
    r"""A collection of request handlers that make up a web application.

    Instances of this class are callable and can be passed directly to
    HTTPServer to serve the application::

        application = web.Application([
            (r"/", MainPageHandler),
        ])
        http_server = httpserver.HTTPServer(application)
        http_server.listen(8080)

    The constructor for this class takes in a list of `~.routing.Rule`
    objects or tuples of values corresponding to the arguments of
    `~.routing.Rule` constructor: ``(matcher, target, [target_kwargs], [name])``,
    the values in square brackets being optional. The default matcher is
    `~.routing.PathMatches`, so ``(regexp, target)`` tuples can also be used
    instead of ``(PathMatches(regexp), target)``.

    A common routing target is a `RequestHandler` subclass, but you can also
    use lists of rules as a target, which create a nested routing configuration::

        application = web.Application([
            (HostMatches("example.com"), [
                (r"/", MainPageHandler),
                (r"/feed", FeedHandler),
            ]),
        ])

    In addition to this you can use nested `~.routing.Router` instances,
    `~.httputil.HTTPMessageDelegate` subclasses and callables as routing targets
    (see `~.routing` module docs for more information).

    When we receive requests, we iterate over the list in order and
    instantiate an instance of the first request class whose regexp
    matches the request path. The request class can be specified as
    either a class object or a (fully-qualified) name.

    A dictionary may be passed as the third element (``target_kwargs``)
    of the tuple, which will be used as keyword arguments to the handler's
    constructor and `~RequestHandler.initialize` method. This pattern
    is used for the `StaticFileHandler` in this example (note that a
    `StaticFileHandler` can be installed automatically with the
    static_path setting described below)::

        application = web.Application([
            (r"/static/(.*)", web.StaticFileHandler, {"path": "/var/www"}),
        ])

    We support virtual hosts with the `add_handlers` method, which takes in
    a host regular expression as the first argument::

        application.add_handlers(r"www\.myhost\.com", [
            (r"/article/([0-9]+)", ArticleHandler),
        ])

    If there's no match for the current request's host, then ``default_host``
    parameter value is matched against host regular expressions.


    .. warning::

       Applications that do not use TLS may be vulnerable to :ref:`DNS
       rebinding <dnsrebinding>` attacks. This attack is especially
       relevant to applications that only listen on ``127.0.0.1`` or
       other private networks. Appropriate host patterns must be used
       (instead of the default of ``r'.*'``) to prevent this risk. The
       ``default_host`` argument must not be used in applications that
       may be vulnerable to DNS rebinding.

    You can serve static files by sending the ``static_path`` setting
    as a keyword argument. We will serve those files from the
    ``/static/`` URI (this is configurable with the
    ``static_url_prefix`` setting), and we will serve ``/favicon.ico``
    and ``/robots.txt`` from the same directory.  A custom subclass of
    `StaticFileHandler` can be specified with the
    ``static_handler_class`` setting.

    .. versionchanged:: 4.5
       Integration with the new `tornado.routing` module.

    """

    def __init__(
        self,
        handlers: Optional[_RuleList] = None,
        default_host: Optional[str] = None,
        **settings: Any,
    ) -> None:
        self.default_host = default_host
        self.settings = settings
        if self.settings.get("static_path"):
            path = self.settings["static_path"]
            handlers = list(handlers or [])
            static_url_prefix = settings.get("static_url_prefix", "/static/")
            static_handler_class = settings.get(
                "static_handler_class", StaticFileHandler
            )
            static_handler_args = settings.get("static_handler_args", {})
            static_handler_args["path"] = path
            for pattern in [
                re.escape(static_url_prefix) + r"(.*)",
                r"/(favicon\.ico)",
                r"/(robots\.txt)",
            ]:
                handlers.insert(0, (pattern, static_handler_class, static_handler_args))

        self.wildcard_router = _ApplicationRouter(self, handlers)
        self.default_router = _ApplicationRouter(
            self, [Rule(AnyMatches(), self.wildcard_router)]
        )

    def find_handler(
        self, request: httputil.HTTPServerRequest, **kwargs: Any
    ) -> "_HandlerDelegate":
        route = self.default_router.find_handler(request)
        if route is not None:
            return cast("_HandlerDelegate", route)

        if self.settings.get("default_handler_class"):
            return self.get_handler_delegate(
                request,
                self.settings["default_handler_class"],
                self.settings.get("default_handler_args", {}),
            )

        return self.get_handler_delegate(request, ErrorHandler, {"status_code": 404})

    def get_handler_delegate(
        self,
        request: httputil.HTTPServerRequest,
        target_class: Type[RequestHandler],
        target_kwargs: Optional[Dict[str, Any]] = None,
        path_args: Optional[List[bytes]] = None,
        path_kwargs: Optional[Dict[str, bytes]] = None,
    ) -> "_HandlerDelegate":
        """Returns `~.httputil.HTTPMessageDelegate` that can serve a request
        for application and `RequestHandler` subclass.

        :arg httputil.HTTPServerRequest request: current HTTP request.
        :arg RequestHandler target_class: a `RequestHandler` class.
        :arg dict target_kwargs: keyword arguments for ``target_class`` constructor.
        :arg list path_args: positional arguments for ``target_class`` HTTP method that
            will be executed while handling a request (``get``, ``post`` or any other).
        :arg dict path_kwargs: keyword arguments for ``target_class`` HTTP method.
        """
        return _HandlerDelegate(
            self, request, target_class, target_kwargs, path_args, path_kwargs
        )

    def log_request(self, handler: RequestHandler) -> None:
        """Writes a completed HTTP request to the logs."""
        if handler.get_status() < 400:
            log_method = LOGGER.info
        elif handler.get_status() < 500:
            log_method = LOGGER.warning
        else:
            log_method = LOGGER.error
        request_time = 1000.0 * handler.request.request_time()
        log_method(
            "%d %s %.2fms",
            handler.get_status(),
            handler._request_summary(),
            request_time,
        )


class _HandlerDelegate(httputil.HTTPMessageDelegate):
    def __init__(
        self,
        application: Application,
        request: httputil.HTTPServerRequest,
        handler_class: Type[RequestHandler],
        handler_kwargs: Optional[Dict[str, Any]],
        path_args: Optional[List[bytes]],
        path_kwargs: Optional[Dict[str, bytes]],
    ) -> None:
        self.application = application
        self.connection = request.connection
        self.request = request
        self.handler_class = handler_class
        self.handler_kwargs = handler_kwargs or {}
        self.path_args = path_args or []
        self.path_kwargs = path_kwargs or {}
        self.chunks = []  # type: List[bytes]

    def headers_received(
        self,
        start_line: Union[httputil.RequestStartLine, httputil.ResponseStartLine],
        headers: httputil.HTTPHeaders,
    ) -> Optional[Awaitable[None]]:
        return None

    def finish(self) -> None:
        # Note that the body gets parsed in RequestHandler._execute so it can be in
        # the right exception handler scope.
        self.request.body = b"".join(self.chunks)
        self.execute()

    def execute(self) -> Optional[Awaitable[None]]:
        if not self.application.settings.get("static_hash_cache", True):
            static_handler_class = self.application.settings.get(
                "static_handler_class", StaticFileHandler
            )
            static_handler_class.reset()

        self.handler = self.handler_class(
            self.application, self.request, **self.handler_kwargs
        )

        # Note that if an exception escapes handler._execute it will be
        # trapped in the Future it returns (which we are ignoring here,
        # leaving it to be logged when the Future is GC'd).
        # However, that shouldn't happen because _execute has a blanket
        # except handler, and we cannot easily access the IOLoop here to
        # call add_future (because of the requirement to remain compatible
        # with WSGI)
        fut = gen.convert_yielded(
            self.handler._execute(*self.path_args, **self.path_kwargs)
        )
        fut.add_done_callback(lambda f: f.result())
        # If we are streaming the request body, then execute() is finished
        # when the handler has prepared to receive the body.  If not,
        # it doesn't matter when execute() finishes (so we return None)
        return self.handler._prepared_future


class HTTPError(Exception):
    """An exception that will turn into an HTTP error response.

    Raising an `HTTPError` is a convenient alternative to calling
    `RequestHandler.send_error` since it automatically ends the
    current function.

    To customize the response sent with an `HTTPError`, override
    `RequestHandler.write_error`.

    :arg int status_code: HTTP status code.  Must be listed in
        `httplib.responses <http.client.responses>` unless the ``reason``
        keyword argument is given.
    :arg str log_message: Message to be written to the log for this error
        (will not be shown to the user unless the `Application` is in debug
        mode).  May contain ``%s``-style placeholders, which will be filled
        in with remaining positional parameters.
    :arg str reason: Keyword-only argument.  The HTTP "reason" phrase
        to pass in the status line along with ``status_code``.  Normally
        determined automatically from ``status_code``, but can be used
        to use a non-standard numeric code.
    """

    def __init__(
        self,
        status_code: int = 500,
        log_message: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.status_code = status_code
        self._log_message = log_message
        self.args = args
        self.reason = kwargs.get("reason", None)

    @property
    def log_message(self) -> Optional[str]:
        """
        A backwards compatible way of accessing log_message.
        """
        if self._log_message and not self.args:
            return self._log_message.replace("%", "%%")
        return self._log_message

    def get_message(self) -> Optional[str]:
        if self._log_message and self.args:
            return self._log_message % self.args
        return self._log_message

    def __str__(self) -> str:
        message = "HTTP %d: %s" % (
            self.status_code,
            self.reason or httputil.responses.get(self.status_code, "Unknown"),
        )
        log_message = self.get_message()
        if log_message:
            return message + " (" + log_message + ")"
        else:
            return message


class Finish(Exception):
    """An exception that ends the request without producing an error response.

    When `Finish` is raised in a `RequestHandler`, the request will
    end (calling `RequestHandler.finish` if it hasn't already been
    called), but the error-handling methods (including
    `RequestHandler.write_error`) will not be called.

    If `Finish()` was created with no arguments, the pending response
    will be sent as-is. If `Finish()` was given an argument, that
    argument will be passed to `RequestHandler.finish()`.

    This can be a more convenient way to implement custom error pages
    than overriding ``write_error`` (especially in library code)::

        if self.current_user is None:
            self.set_status(401)
            self.set_header('WWW-Authenticate', 'Basic realm="something"')
            raise Finish()

    .. versionchanged:: 4.3
       Arguments passed to ``Finish()`` will be passed on to
       `RequestHandler.finish`.
    """

    pass


class MissingArgumentError(HTTPError):
    """Exception raised by `RequestHandler.get_argument`.

    This is a subclass of `HTTPError`, so if it is uncaught a 400 response
    code will be used instead of 500 (and a stack trace will not be logged).

    .. versionadded:: 3.1
    """

    def __init__(self, arg_name: str) -> None:
        super().__init__(400, "Missing argument %s" % arg_name)
        self.arg_name = arg_name


class ErrorHandler(RequestHandler):
    """Generates an error response with ``status_code`` for all requests."""

    def initialize(self, status_code: int) -> None:
        self.set_status(status_code)

    def prepare(self) -> None:
        raise HTTPError(self._status_code)


class StaticFileHandler(RequestHandler):
    """A simple handler that can serve static content from a directory.

    A `StaticFileHandler` is configured automatically if you pass the
    ``static_path`` keyword argument to `Application`.  This handler
    can be customized with the ``static_url_prefix``, ``static_handler_class``,
    and ``static_handler_args`` settings.

    To map an additional path to this handler for a static data directory
    you would add a line to your application like::

        application = web.Application([
            (r"/content/(.*)", web.StaticFileHandler, {"path": "/var/www"}),
        ])

    The handler constructor requires a ``path`` argument, which specifies the
    local root directory of the content to be served.

    Note that a capture group in the regex is required to parse the value for
    the ``path`` argument to the get() method (different than the constructor
    argument above); see `URLSpec` for details.

    To serve a file like ``index.html`` automatically when a directory is
    requested, set ``static_handler_args=dict(default_filename="index.html")``
    in your application settings, or add ``default_filename`` as an initializer
    argument for your ``StaticFileHandler``.

    To maximize the effectiveness of browser caching, this class supports
    versioned urls (by default using the argument ``?v=``).  If a version
    is given, we instruct the browser to cache this file indefinitely.
    `make_static_url` (also available as `RequestHandler.static_url`) can
    be used to construct a versioned url.

    This handler is intended primarily for use in development and light-duty
    file serving; for heavy traffic it will be more efficient to use
    a dedicated static file server (such as nginx or Apache).  We support
    the HTTP ``Accept-Ranges`` mechanism to return partial content (because
    some browsers require this functionality to be present to seek in
    HTML5 audio or video).

    **Subclassing notes**

    This class is designed to be extensible by subclassing, but because
    of the way static urls are generated with class methods rather than
    instance methods, the inheritance patterns are somewhat unusual.
    Be sure to use the ``@classmethod`` decorator when overriding a
    class method.  Instance methods may use the attributes ``self.path``
    ``self.absolute_path``, and ``self.modified``.

    Subclasses should only override methods discussed in this section;
    overriding other methods is error-prone.  Overriding
    ``StaticFileHandler.get`` is particularly problematic due to the
    tight coupling with ``compute_etag`` and other methods.

    To change the way static urls are generated (e.g. to match the behavior
    of another server or CDN), override `make_static_url`, `parse_url_path`,
    `get_cache_time`, and/or `get_version`.

    To replace all interaction with the filesystem (e.g. to serve
    static content from a database), override `get_content`,
    `get_content_size`, `get_modified_time`, `get_absolute_path`, and
    `validate_absolute_path`.

    .. versionchanged:: 3.1
       Many of the methods for subclasses were added in Tornado 3.1.
    """

    CACHE_MAX_AGE = 86400 * 365 * 10  # 10 years

    _static_hashes = {}  # type: Dict[str, Optional[str]]
    _lock = threading.Lock()  # protects _static_hashes

    def initialize(self, path: str, default_filename: Optional[str] = None) -> None:
        self.root = path
        self.default_filename = default_filename

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._static_hashes = {}

    def head(self, path: str) -> Awaitable[None]:
        return self.get(path, include_body=False)

    async def get(self, path: str, include_body: bool = True) -> None:
        # Set up our path instance variables.
        self.path = self.parse_url_path(path)
        del path  # make sure we don't refer to path instead of self.path again
        absolute_path = self.get_absolute_path(self.root, self.path)
        self.absolute_path = self.validate_absolute_path(self.root, absolute_path)
        if self.absolute_path is None:
            return

        self.modified = self.get_modified_time()
        self.set_headers()

        if self.should_return_304():
            self.set_status(304)
            return

        size = self.get_content_size()
        start = end = None

        content_length = size
        self.set_header("Content-Length", content_length)

        if include_body:
            content = self.get_content(self.absolute_path, start, end)
            if isinstance(content, bytes):
                content = [content]
            for chunk in content:
                try:
                    self.write(chunk)
                    await self.flush()
                except iostream.StreamClosedError:
                    return
        else:
            assert self.request.method == "HEAD"

    def compute_etag(self) -> Optional[str]:
        """Sets the ``Etag`` header based on static url version.

        This allows efficient ``If-None-Match`` checks against cached
        versions, and sends the correct ``Etag`` for a partial response
        (i.e. the same ``Etag`` as the full file).

        .. versionadded:: 3.1
        """
        assert self.absolute_path is not None
        version_hash = self._get_cached_version(self.absolute_path)
        if not version_hash:
            return None
        return f'"{version_hash}"'

    def set_headers(self) -> None:
        """Sets the content and caching headers on the response.

        .. versionadded:: 3.1
        """
        self.set_header("Accept-Ranges", "bytes")
        self.set_etag_header()

        if self.modified is not None:
            self.set_header("Last-Modified", self.modified)

        content_type = self.get_content_type()
        if content_type:
            self.set_header("Content-Type", content_type)

        cache_time = self.get_cache_time(self.path, self.modified, content_type)
        if cache_time > 0:
            self.set_header(
                "Expires",
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(seconds=cache_time),
            )
            self.set_header("Cache-Control", "max-age=" + str(cache_time))

        self.set_extra_headers(self.path)

    def should_return_304(self) -> bool:
        """Returns True if the headers indicate that we should return 304.

        .. versionadded:: 3.1
        """
        # If client sent If-None-Match, use it, ignore If-Modified-Since
        if self.request.headers.get("If-None-Match"):
            return self.check_etag_header()

        # Check the If-Modified-Since, and don't send the result if the
        # content has not been modified
        ims_value = self.request.headers.get("If-Modified-Since")
        if ims_value is not None:
            try:
                if_since = email.utils.parsedate_to_datetime(ims_value)
            except Exception:
                return False
            if if_since.tzinfo is None:
                if_since = if_since.replace(tzinfo=datetime.timezone.utc)
            assert self.modified is not None
            if if_since >= self.modified:
                return True

        return False

    @classmethod
    def get_absolute_path(cls, root: str, path: str) -> str:
        """Returns the absolute location of ``path`` relative to ``root``.

        ``root`` is the path configured for this `StaticFileHandler`
        (in most cases the ``static_path`` `Application` setting).

        This class method may be overridden in subclasses.  By default
        it returns a filesystem path, but other strings may be used
        as long as they are unique and understood by the subclass's
        overridden `get_content`.

        .. versionadded:: 3.1
        """
        abspath = os.path.abspath(os.path.join(root, path))
        return abspath

    def validate_absolute_path(self, root: str, absolute_path: str) -> Optional[str]:
        """Validate and return the absolute path.

        ``root`` is the configured path for the `StaticFileHandler`,
        and ``path`` is the result of `get_absolute_path`

        This is an instance method called during request processing,
        so it may raise `HTTPError` or use methods like
        `RequestHandler.redirect` (return None after redirecting to
        halt further processing).  This is where 404 errors for missing files
        are generated.

        This method may modify the path before returning it, but note that
        any such modifications will not be understood by `make_static_url`.

        In instance methods, this method's result is available as
        ``self.absolute_path``.

        .. versionadded:: 3.1
        """
        # os.path.abspath strips a trailing /.
        # We must add it back to `root` so that we only match files
        # in a directory named `root` instead of files starting with
        # that prefix.
        root = os.path.abspath(root)
        if not root.endswith(os.path.sep):
            # abspath always removes a trailing slash, except when
            # root is '/'. This is an unusual case, but several projects
            # have independently discovered this technique to disable
            # Tornado's path validation and (hopefully) do their own,
            # so we need to support it.
            root += os.path.sep
        # The trailing slash also needs to be temporarily added back
        # the requested path so a request to root/ will match.
        if not (absolute_path + os.path.sep).startswith(root):
            raise HTTPError(403, "%s is not in root static directory", self.path)
        if os.path.isdir(absolute_path) and self.default_filename is not None:
            # need to look at the request.path here for when path is empty
            # but there is some prefix to the path that was already
            # trimmed by the routing
            absolute_path = os.path.join(absolute_path, self.default_filename)
        if not os.path.exists(absolute_path):
            raise HTTPError(404)
        if not os.path.isfile(absolute_path):
            raise HTTPError(403, "%s is not a file", self.path)
        return absolute_path

    @classmethod
    def get_content(
        cls, abspath: str, start: Optional[int] = None, end: Optional[int] = None
    ) -> Generator[bytes, None, None]:
        """Retrieve the content of the requested resource which is located
        at the given absolute path.

        This class method may be overridden by subclasses.  Note that its
        signature is different from other overridable class methods
        (no ``settings`` argument); this is deliberate to ensure that
        ``abspath`` is able to stand on its own as a cache key.

        This method should either return a byte string or an iterator
        of byte strings.  The latter is preferred for large files
        as it helps reduce memory fragmentation.

        .. versionadded:: 3.1
        """
        with open(abspath, "rb") as file:
            if start is not None:
                file.seek(start)
            if end is not None:
                remaining = end - (start or 0)  # type: Optional[int]
            else:
                remaining = None
            while True:
                chunk_size = 64 * 1024
                if remaining is not None and remaining < chunk_size:
                    chunk_size = remaining
                chunk = file.read(chunk_size)
                if chunk:
                    if remaining is not None:
                        remaining -= len(chunk)
                    yield chunk
                else:
                    if remaining is not None:
                        assert remaining == 0
                    return

    @classmethod
    def get_content_version(cls, abspath: str) -> str:
        """Returns a version string for the resource at the given path.

        This class method may be overridden by subclasses.  The
        default implementation is a SHA-512 hash of the file's contents.

        .. versionadded:: 3.1
        """
        data = cls.get_content(abspath)
        hasher = hashlib.sha512()
        if isinstance(data, bytes):
            hasher.update(data)
        else:
            for chunk in data:
                hasher.update(chunk)
        return hasher.hexdigest()

    def _stat(self) -> os.stat_result:
        assert self.absolute_path is not None
        if not hasattr(self, "_stat_result"):
            self._stat_result = os.stat(self.absolute_path)
        return self._stat_result

    def get_content_size(self) -> int:
        """Retrieve the total size of the resource at the given path.

        This method may be overridden by subclasses.

        .. versionadded:: 3.1

        .. versionchanged:: 4.0
           This method is now always called, instead of only when
           partial results are requested.
        """
        stat_result = self._stat()
        return stat_result.st_size

    def get_modified_time(self) -> Optional[datetime.datetime]:
        """Returns the time that ``self.absolute_path`` was last modified.

        May be overridden in subclasses.  Should return a `~datetime.datetime`
        object or None.

        .. versionadded:: 3.1

        .. versionchanged:: 6.4
           Now returns an aware datetime object instead of a naive one.
           Subclasses that override this method may return either kind.
        """
        stat_result = self._stat()
        # NOTE: Historically, this used stat_result[stat.ST_MTIME],
        # which truncates the fractional portion of the timestamp. It
        # was changed from that form to stat_result.st_mtime to
        # satisfy mypy (which disallows the bracket operator), but the
        # latter form returns a float instead of an int. For
        # consistency with the past (and because we have a unit test
        # that relies on this), we truncate the float here, although
        # I'm not sure that's the right thing to do.
        modified = datetime.datetime.fromtimestamp(
            int(stat_result.st_mtime), datetime.timezone.utc
        )
        return modified

    def get_content_type(self) -> str:
        """Returns the ``Content-Type`` header to be used for this request.

        .. versionadded:: 3.1
        """
        assert self.absolute_path is not None
        mime_type, encoding = mimetypes.guess_type(self.absolute_path)
        # As of 2015-07-21 there is no bzip2 encoding defined at
        # http://www.iana.org/assignments/media-types/media-types.xhtml
        # So for that (and any other encoding), use octet-stream.
        if encoding is not None:
            return "application/octet-stream"
        elif mime_type is not None:
            return mime_type
        # if mime_type not detected, use application/octet-stream
        else:
            return "application/octet-stream"

    def set_extra_headers(self, path: str) -> None:
        """For subclass to add extra headers to the response"""
        pass

    def get_cache_time(
        self, path: str, modified: Optional[datetime.datetime], mime_type: str
    ) -> int:
        """Override to customize cache control behavior.

        Return a positive number of seconds to make the result
        cacheable for that amount of time or 0 to mark resource as
        cacheable for an unspecified amount of time (subject to
        browser heuristics).

        By default returns cache expiry of 10 years for resources requested
        with ``v`` argument.
        """
        return self.CACHE_MAX_AGE if "v" in self.request.arguments else 0

    def parse_url_path(self, url_path: str) -> str:
        """Converts a static URL path into a filesystem path.

        ``url_path`` is the path component of the URL with
        ``static_url_prefix`` removed.  The return value should be
        filesystem path relative to ``static_path``.

        This is the inverse of `make_static_url`.
        """
        if os.path.sep != "/":
            url_path = url_path.replace("/", os.path.sep)
        return url_path

    @classmethod
    def _get_cached_version(cls, abs_path: str) -> Optional[str]:
        with cls._lock:
            hashes = cls._static_hashes
            if abs_path not in hashes:
                try:
                    hashes[abs_path] = cls.get_content_version(abs_path)
                except Exception:
                    LOGGER.error("Could not open static file %r", abs_path)
                    hashes[abs_path] = None
            hsh = hashes.get(abs_path)
            if hsh:
                return hsh
        return None
