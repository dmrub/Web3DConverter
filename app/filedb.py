# This file is part of Web3DConverter. It is subject to the license terms in
# the LICENSE file found in the top-level directory of this distribution.
# You may not use this file except in compliance with the License.

import fasteners
import os
import os.path
import threading
import json
import six
import shutil
from utils import obj_merge


class FileEntry(object):
    def __init__(self, fdb, name, data=None, move_from=None, copy_from=None):
        assert data is None or isinstance(data, dict)
        self._name = name
        self._path = os.path.join(fdb.path, name)
        self.thread_lock = threading.RLock()
        self.process_lock = fasteners.InterProcessLock(self._path + '.lock')

        with self.process_lock:
            if move_from:
                shutil.move(move_from, self._path)
            elif copy_from:
                shutil.copy2(copy_from, self._path)
            elif not os.path.exists(self._path):
                open(self._path, 'a').close()

        self.data_path = self._path + '.data'
        self.data = data
        self.disk_data = None
        self.sync()

    def exists(self):
        return os.path.exists(self._path)

    @property
    def name(self):
        return self._name

    @property
    def path(self):
        return self._path

    def remove(self):
        with self.thread_lock:
            with self.process_lock:
                os.remove(self._path)

    def sync(self):
        with self.thread_lock:
            with self.process_lock:
                if os.path.exists(self.data_path):
                    with open(self.data_path, 'r') as fd:
                        try:
                            self.disk_data = json.load(fd)
                        except:
                            pass
                if self.disk_data is None:
                    self.disk_data = {}
                if self.data is None:
                    self.data = self.disk_data.copy()
                if self.disk_data != self.data:
                    self.data = obj_merge(self.data, self.disk_data)
                    with open(self.data_path, 'w') as fd:
                        json.dump(self.data, fd, separators=(',', ':'))
                    self.disk_data = self.data.copy()

    def update_data(self, new_data):
        with self.thread_lock:
            if self.data is None:
                self.data = new_data.copy()
            else:
                self.data.update(new_data)
            self.sync()

    def get(self, key, default=None):
        with self.thread_lock:
            self.sync()
            return self.data.get(key, default)

    def __setitem__(self, key, value):
        with self.thread_lock:
            self.data[key] = value
            self.sync()

    def __getitem__(self, item):
        with self.thread_lock:
            self.sync()
            return self.data[item]

    def __delitem__(self, key):
        with self.thread_lock:
            del self.data[key]
            self.sync()

    def close(self):
        self.sync()

    def __repr__(self):
        return 'FileEntry(name={!r}, data={!r})'.format(self.name, self.data)


class FileDB(object):
    def __init__(self, path):
        self.path = path
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        self.thread_lock = threading.RLock()
        self.process_lock = fasteners.InterProcessLock(os.path.join(self.path, '.lock'))
        self.entries = {}
        self.sync()

    def sync(self):
        with self.thread_lock:
            with self.process_lock:
                if os.path.exists(self.path):
                    lock_files = set()
                    data_files = set()
                    checked_entries = set()
                    for fname in os.listdir(self.path):
                        fpath = os.path.join(self.path, fname)
                        is_lock = fname.endswith('.lock')
                        is_data = fname.endswith('.data')
                        is_dir = os.path.isdir(fpath)
                        if fname.startswith('.'):
                            pass
                        elif not is_lock and not is_data and not is_dir:
                            entry = self.entries.get(fname, None)
                            if entry is None:
                                entry = FileEntry(fdb=self, name=fname)
                                self.entries[fname] = entry
                            else:
                                entry.sync()
                            checked_entries.add(fname)
                        elif is_lock:
                            lock_files.add(fname)
                        elif is_data:
                            data_files.add(fname)

                    remove_entries = set()
                    for entry_name in six.iterkeys(self.entries):
                        if entry_name not in checked_entries:
                            remove_entries.add(entry_name)

                    for entry_name in remove_entries:
                        self.entries[entry_name].close()
                        del self.entries[entry_name]

                    for fname in lock_files:
                        if fname[:-5] not in self.entries:
                            os.remove(os.path.join(self.path, fname))
                    for fname in data_files:
                        if fname[:-5] not in self.entries:
                            os.remove(os.path.join(self.path, fname))

    def __contains__(self, item):
        with self.thread_lock:
            return item in self.entries

    def get(self, name, default=None):
        with self.thread_lock:
            return self.entries.get(name, default)

    def get_or_create(self, name, data=None, move_from=None, copy_from=None):
        with self.thread_lock:
            entry = self.entries.get(name, None)
            if not entry:
                with self.process_lock:
                    entry = FileEntry(fdb=self, name=name, data=data, move_from=move_from, copy_from=copy_from)
                    self.entries[name] = entry
            return entry

    def close(self):
        with self.thread_lock:
            with self.process_lock:
                for entry in six.itervalues(self.entries):
                    entry.close()
                self.entries.clear()
