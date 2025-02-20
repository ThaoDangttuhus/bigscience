# This file is part of pymarc. It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution and at
# https://opensource.org/licenses/BSD-2-Clause. pymarc may be copied, modified,
# propagated, or distributed according to the terms contained in the LICENSE
# file.

"""Pymarc Reader."""
import os
import sys
import json

from io import IOBase, BytesIO, StringIO
from typing import Callable, BinaryIO, IO, Iterator, Union

from pymarc.constants import END_OF_RECORD
from pymarc import Record, Field
from pymarc import exceptions


class Reader:
    """A base class for all iterating readers in the pymarc package."""

    def __iter__(self):
        return self


class MARCReader(Reader):
    """An iterator class for reading a file of MARC21 records.

    Simple usage:

    .. code-block:: python

        from pymarc import MARCReader

        ## pass in a file object
        reader = MARCReader(open('file.dat', 'rb'))
        for record in reader:
            ...

        ## pass in marc in transmission format
        reader = MARCReader(rawmarc)
        for record in reader:
            ...

    If you would like to have your Record object contain unicode strings
    use the to_unicode parameter:

    .. code-block:: python

        reader = MARCReader(open('file.dat', 'rb'), to_unicode=True)

    This will decode from MARC-8 or UTF-8 depending on the value in the
    MARC leader at position 9.

    If you find yourself in the unfortunate position of having data that
    is utf-8 encoded without the leader set appropriately you can use
    the force_utf8 parameter:

    .. code-block:: python

        reader = MARCReader(open('file.dat', 'rb'), to_unicode=True,
            force_utf8=True)

    If you find yourself in the unfortunate position of having data that is
    mostly utf-8 encoded but with a few non-utf-8 characters, you can also use
    the utf8_handling parameter, which takes the same values ('strict',
    'replace', and 'ignore') as the Python Unicode codecs (see
    http://docs.python.org/library/codecs.html for more info).

    Although, it's not legal in MARC-21 to use anything but MARC-8 or UTF-8, but
    if you have a file in incorrect encode and you know what it is, you can
    try to use your encode in parameter "file_encoding".

    MARCReader parses data in a permissive way and gives the user full control
    on what to do in case wrong record is encountered. Whenever any error is
    found reader returns ``None`` instead of regular record object.
    The exception information and corresponding data are available through
    reader.current_exception and reader.current_chunk properties:

    .. code-block:: python

        reader = MARCReader(open('file.dat', 'rb'))
        for record in reader:
            if record is None:
                print(
                    "Current chunk: ",
                    reader.current_chunk,
                    " was ignored because the following exception raised: ",
                    reader.current_exception
                )
            else:
                # do something with record
    """

    _current_chunk = None
    _current_exception = None

    file_handle: IO

    @property
    def current_chunk(self):
        """Current chunk."""
        return self._current_chunk

    @property
    def current_exception(self):
        """Current exception."""
        return self._current_exception

    def __init__(
        self,
        marc_target: Union[BinaryIO, bytes],
        to_unicode: bool = True,
        force_utf8: bool = False,
        hide_utf8_warnings: bool = False,
        utf8_handling: str = "strict",
        file_encoding: str = "iso8859-1",
        permissive: bool = False,
    ) -> None:
        """The constructor to which you can pass either raw marc or a file-like object.

        Basically the argument you pass in should be raw MARC in transmission format or
        an object that responds to read().
        """
        super(MARCReader, self).__init__()
        self.to_unicode = to_unicode
        self.force_utf8 = force_utf8
        self.hide_utf8_warnings = hide_utf8_warnings
        self.utf8_handling = utf8_handling
        self.file_encoding = file_encoding
        self.permissive = permissive
        if isinstance(marc_target, bytes):
            self.file_handle = BytesIO(marc_target)
        else:
            self.file_handle = marc_target

    def close(self) -> None:
        """Close the handle."""
        self.file_handle.close()

    def __next__(self):
        """Read and parse the next record."""
        if self._current_exception:
            if isinstance(self._current_exception, exceptions.FatalReaderEror):
                raise StopIteration

        self._current_chunk = None
        self._current_exception = None

        self._current_chunk = first5 = self.file_handle.read(5)
        if not first5:
            raise StopIteration

        if len(first5) < 5:
            self._current_exception = exceptions.TruncatedRecord()
            return

        try:
            length = int(first5)
        except ValueError:
            self._current_exception = exceptions.RecordLengthInvalid()
            return

        chunk = self.file_handle.read(length - 5)
        chunk = first5 + chunk
        self._current_chunk = chunk

        if len(self._current_chunk) < length:
            self._current_exception = exceptions.TruncatedRecord()
            return

        if self._current_chunk[-1] != ord(END_OF_RECORD):
            self._current_exception = exceptions.EndOfRecordNotFound()
            return

        try:
            return Record(
                chunk,
                to_unicode=self.to_unicode,
                force_utf8=self.force_utf8,
                hide_utf8_warnings=self.hide_utf8_warnings,
                utf8_handling=self.utf8_handling,
                file_encoding=self.file_encoding,
            )
        except Exception as ex:
            self._current_exception = ex


def map_records(f: Callable, *files: BytesIO) -> None:
    """Applies a given function to each record in a batch.

    You can pass in multiple batches.

    .. code-block:: python

        def print_title(r):
            print(r['245'])
        map_records(print_title, file('marc.dat'))
    """
    for file in files:
        list(map(f, MARCReader(file)))


class JSONReader(Reader):
    """JSON Reader."""

    file_handle: IO

    def __init__(
        self,
        marc_target: Union[bytes, str],
        encoding: str = "utf-8",
        stream: bool = False,
    ) -> None:
        """The constructor to which you can pass either raw marc or a file-like object.

        Basically the argument you pass in should be raw JSON in transmission format or
        an object that responds to read().
        """
        self.encoding = encoding
        if isinstance(marc_target, IOBase):
            self.file_handle = marc_target
        else:
            if os.path.exists(marc_target):
                self.file_handle = open(marc_target, "r")
            else:
                self.file_handle = StringIO(marc_target)  # type: ignore
        if stream:
            sys.stderr.write(
                "Streaming not yet implemented, your data will be loaded into memory\n"
            )
        self.records = json.load(self.file_handle, strict=False)

    def __iter__(self) -> Iterator:
        if hasattr(self.records, "__iter__") and not isinstance(self.records, dict):
            self.iter = iter(self.records)
        else:
            self.iter = iter([self.records])
        return self

    def __next__(self) -> Iterator:
        jobj = next(self.iter)
        rec = Record()
        rec.leader = jobj["leader"]
        for field in jobj["fields"]:
            k, v = list(field.items())[0]
            if "subfields" in v and hasattr(v, "update"):
                # flatten m-i-j dict to list in pymarc
                subfields: list = []
                for sub in v["subfields"]:
                    for code, value in sub.items():
                        subfields.extend((code, value))
                fld = Field(
                    tag=k, subfields=subfields, indicators=[v["ind1"], v["ind2"]]
                )
            else:
                fld = Field(tag=k, data=v)
            rec.add_field(fld)
        return rec
