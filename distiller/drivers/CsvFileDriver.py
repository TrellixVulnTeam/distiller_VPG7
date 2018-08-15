import os
import csv
import shutil

from distiller.api.Reader import Reader, ReadIterator
from distiller.api.Writer import Writer, WriteModes, WriteAfterCommitException
from distiller.drivers.internal.FileDriver import FileDriver, get_temp_path
from distiller.drivers.BinaryFileDriver import BlobIterator


class CsvFileDriver(FileDriver):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def read(self, spirit, config):
        return FileReader(self._get_data_path(spirit, config), **self.kwargs)

    def write(self, spirit, config):
        data_path = self._get_data_path(spirit, config, create_path=True)

        return CsvWriteModes(data_path, **self.kwargs)


class FileReader(Reader):
    def __init__(self, file_path, **kwargs):
        self.file_path = file_path
        self.kwargs = kwargs

    def blob(self):
        return BlobIterator(self.file_path, mode="r", **self.kwargs)

    def it(self):
        """Returns a relational row-based iterator"""

        return RowIterator(self.file_path, **self.kwargs)


class RowIterator(ReadIterator):
    def __init__(self, file_path, **kwargs):
        self.file_path = file_path
        self.file = None
        self.kwargs = kwargs

    def __enter__(self):
        self.file = open(self.file_path, "r", **self.kwargs.get("file_params", {}))

        if self.kwargs.get("dict", False):
            self.reader = csv.DictReader(self.file, **self.kwargs.get("csv_params", {}))
        else:
            self.reader = csv.reader(self.file, **self.kwargs.get("csv_params", {}))

        return self

    def __exit__(self, type, value, traceback):
        if self.file is not None and not self.file.closed:
            self.file.close()

    def __iter__(self):
        if self.file is None:
            raise RuntimeError("RowIterator must be entered with with-statement before usage")

        for row in self.reader:
            yield row


class CsvWriteModes(WriteModes):
    def __init__(self, file_path, **kwargs):
        self.kwargs = kwargs
        self.file_path = file_path

    def replace(self):
        return ReplaceCsvFileWriter(self.file_path, **self.kwargs)

    def update(self, key):
        return UpdateCsvFileWriter(self.file_path, key, **self.kwargs)

    def append(self):
        return AppendCsvFileWriter(self.file_path, **self.kwargs)


class CsvFileWriter(Writer):
    def __init__(self, file_path, **kwargs):
        self.file_path = file_path
        self.kwargs = kwargs
        self.commited = False

    def write(self, data):
        """Write a relational entry, or an entire blob"""

        if self.commited:
            raise WriteAfterCommitException

        self.writer.writerow(data)

    def commit(self):
        """Commits the change. Write operations after this lead to an error"""

        if self.commited:
            raise WriteAfterCommitException

        self.commited = True
        self.file.close()
        self.writer = None
        self.file = None

        shutil.move(get_temp_path(self.file_path), self.file_path)

    def __exit__(self, type, value, traceback):
        """If exit appears without a commit, undo all changes"""

        if not self.commited:
            self.file.close()
            os.remove(get_temp_path(self.file_path))
            self.writer = None
            self.file = None


class ReplaceCsvFileWriter(CsvFileWriter):
    def __enter__(self):
        self.file = open(get_temp_path(self.file_path), "w", **self.kwargs.get("file_params", {}))

        if self.kwargs.get("dict", False):
            self.writer = csv.DictWriter(
                self.file,
                self.kwargs.get("fields", []),
                **self.kwargs.get("csv_params", {})
            )
            self.writer.writeheader()
        else:
            self.writer = csv.writer(self.file, **self.kwargs.get("csv_params", {}))

        return self


class AppendCsvFileWriter(CsvFileWriter):
    def __enter__(self):
        self.file = open(get_temp_path(self.file_path), "a", **self.kwargs.get("file_params", {}))

        if self.kwargs.get("dict", False):
            self.writer = csv.DictWriter(
                self.file,
                self.kwargs.get("fields", {}),
                **self.kwargs.get("csv_params", {})
            )
        else:
            self.writer = csv.writer(self.file, **self.kwargs.get("csv_params", {}))

        return self


class UpdateCsvFileWriter(Writer):
    def __init__(self, file_path, key, **kwargs):
        self.file_path = file_path
        self.key = key
        self.kwargs = kwargs
        self.commited = False

        self.columns = []
        self.key_index = {}

    def write(self, data):
        if self.commited:
            raise WriteAfterCommitException

        if data[self.key] in self.key_index:
            self.columns[self.key_index[data[self.key]]] = data
        else:
            self.key_index[data[self.key]] = len(self.columns)
            self.columns.append(data)

    def commit(self):
        """Commits the change. Write operations after this lead to an error"""

        if self.commited:
            raise WriteAfterCommitException

        self.file = open(self.file_path, "w", **self.kwargs.get("file_params", {}))

        self.writer = csv.DictWriter(
            self.file,
            self.kwargs.get("fields", {}),
            **self.kwargs.get("csv_params", {})
        )
        self.writer.writeheader()

        for column in self.columns:
            self.writer.writerow(column)

    def __enter__(self):
        if os.path.exists(self.file_path):
            with open(self.file_path) as f:
                reader = csv.DictReader(f, **self.kwargs.get("csv_params", {}))
                i = 0

                for row in reader:
                    self.key_index[row[self.key]] = i
                    self.columns.append(row)

                    i += 1

        return self

    def __exit__(self, type, value, traceback):
        self.columns = None
        self.key_index = None


module_class = CsvFileDriver
