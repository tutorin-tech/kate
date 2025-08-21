import zlib

from kate.core.exceptions import _DecompressTooLargeError

# Python's GzipFile defaults to level 9, while most other gzip
# tools (including gzip itself) default to 6, which is probably a
# better CPU/size tradeoff.
GZIP_LEVEL = 6

_default_max_message_size = 10 * 1024 * 1024


class _PerMessageDeflateCompressor:
    def __init__(
        self,
        persistent: bool,
        max_wbits,
        compression_options = None,
    ) -> None:
        if max_wbits is None:
            max_wbits = zlib.MAX_WBITS
        # There is no symbolic constant for the minimum wbits value.
        if not (8 <= max_wbits <= zlib.MAX_WBITS):
            raise ValueError(
                "Invalid max_wbits value %r; allowed range 8-%d",
                max_wbits,
                zlib.MAX_WBITS,
            )
        self._max_wbits = max_wbits

        if (
            compression_options is None
            or "compression_level" not in compression_options
        ):
            self._compression_level = GZIP_LEVEL
        else:
            self._compression_level = compression_options["compression_level"]

        if compression_options is None or "mem_level" not in compression_options:
            self._mem_level = 8
        else:
            self._mem_level = compression_options["mem_level"]

        if persistent:
            self._compressor = self._create_compressor()
        else:
            self._compressor = None

    def _create_compressor(self):
        return zlib.compressobj(
            self._compression_level, zlib.DEFLATED, -self._max_wbits, self._mem_level
        )

    def compress(self, data: bytes) -> bytes:
        compressor = self._compressor or self._create_compressor()
        data = compressor.compress(data) + compressor.flush(zlib.Z_SYNC_FLUSH)
        assert data.endswith(b"\x00\x00\xff\xff")
        return data[:-4]


class _PerMessageDeflateDecompressor:
    def __init__(
        self,
        persistent: bool,
        max_wbits,
        max_message_size: int,
        compression_options= None,
    ) -> None:
        self._max_message_size = max_message_size
        if max_wbits is None:
            max_wbits = zlib.MAX_WBITS
        if not (8 <= max_wbits <= zlib.MAX_WBITS):
            raise ValueError(
                "Invalid max_wbits value %r; allowed range 8-%d",
                max_wbits,
                zlib.MAX_WBITS,
            )
        self._max_wbits = max_wbits
        if persistent:
            self._decompressor = (
                self._create_decompressor()
            )
        else:
            self._decompressor = None

    def _create_decompressor(self) :
        return zlib.decompressobj(-self._max_wbits)

    def decompress(self, data: bytes) -> bytes:
        decompressor = self._decompressor or self._create_decompressor()
        result = decompressor.decompress(
            data + b"\x00\x00\xff\xff", self._max_message_size
        )
        if decompressor.unconsumed_tail:
            raise _DecompressTooLargeError()
        return result


class CompressionMixin:

    def _create_compressors(
        self,
        side: str,
        agreed_parameters,
        compression_options = None,
    ) -> None:
        # TODO: handle invalid parameters gracefully
        allowed_keys = {
            "server_no_context_takeover",
            "client_no_context_takeover",
            "server_max_window_bits",
            "client_max_window_bits",
        }
        for key in agreed_parameters:
            if key not in allowed_keys:
                raise ValueError("unsupported compression parameter %r" % key)
        other_side = "client" if (side == "server") else "server"
        self._compressor = _PerMessageDeflateCompressor(
            **self._get_compressor_options(side, agreed_parameters, compression_options)
        )
        self._decompressor = _PerMessageDeflateDecompressor(
            max_message_size=self.settings.get('max_message_size', _default_max_message_size),
            **self._get_compressor_options(
                other_side, agreed_parameters, compression_options
            ),
        )

    @staticmethod
    def _get_compressor_options(side: str, agreed_parameters, compression_options = None):
        """Converts a websocket agreed_parameters set to keyword arguments
        for our compressor objects.
        """
        options = dict(
            persistent=(side + "_no_context_takeover") not in agreed_parameters
        )
        wbits_header = agreed_parameters.get(side + "_max_window_bits", None)
        if wbits_header is None:
            options["max_wbits"] = zlib.MAX_WBITS
        else:
            options["max_wbits"] = int(wbits_header)

        options["compression_options"] = compression_options
        return options
