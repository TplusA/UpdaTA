#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2020  T+A elektroakustik GmbH & Co. KG
#
# This file is part of UpdaTA
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.

from pathlib import Path
import shlex
import subprocess

from .strbo_log import errormsg
from .strbo_version import VersionNumber


def _parse_shell_style_file(path):
    values = {}

    try:
        with path.open('r') as f:
            raw_content = f.read()
            if not raw_content:
                return values

            for line in shlex.split(raw_content):
                key, value = line.split('=', 1)
                if key:
                    values[key] = value
    except Exception as e:
        errormsg('Error reading file {}: {}'.format(path, e))
        values = None

    return values


class VersionInfo:
    def __init__(self, version_number, release_line, flavor,
                 time_stamp, commit_id):
        self._version_number = version_number
        self._release_line = release_line
        self._flavor = flavor
        self._time_stamp = time_stamp
        self._commit_id = commit_id

    def __str__(self):
        return 'Version "{}" Line "{}" Flavor "{}" Time "{}" Commit "{}"' \
               .format(self._version_number, self._release_line, self._flavor,
                       self._time_stamp, self._commit_id)

    def get_release_line(self):
        return self._release_line

    def get_flavor(self):
        return self._flavor

    def get_version_number(self):
        return self._version_number

    @staticmethod
    def from_strbo_release(values):
        return VersionInfo(VersionNumber.from_string(values['STRBO_VERSION']),
                           values['STRBO_RELEASE_LINE'],
                           values['STRBO_FLAVOR'],
                           values['STRBO_DATETIME'],
                           values['STRBO_GIT_COMMIT'])


class MainSystem:
    def __init__(self, etc_path='/etc'):
        self._etc_path = Path(etc_path)

    def get_system_version(self):
        sr = self._etc_path / 'strbo-release'

        try:
            values = _parse_shell_style_file(sr)
            return VersionInfo.from_strbo_release(values)
        except Exception as e:
            errormsg('Failed obtaining main system version from {}: {}'
                     .format(sr, e))
            return None


def run_command(cmd, what=None):
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode == 0:
        return

    if what is None:
        what = ' '.join(cmd)

    errormsg('Command "{}" FAILED: {}'.format(what, proc.stderr))

    raise RuntimeError(
            'Command "{}" returned non-zero exit status {}'
            .format(what, proc.returncode))


class RecoverySystem:
    def __init__(self, system_mountpoint='/bootpartr',
                 data_mountpoint='/src', data_mountpoint_mounted=False):
        self.system_mountpoint = Path(system_mountpoint)
        self.data_mountpoint = Path(data_mountpoint)
        self.data_mountpoint_mounted = data_mountpoint_mounted

    def get_system_version(self):
        sr = self.system_mountpoint / 'strbo-release'

        try:
            values = _parse_shell_style_file(sr)
            return VersionInfo.from_strbo_release(values)
        except Exception as e:
            errormsg('Failed obtaining recovery system version from {}: {}'
                     .format(sr, e))
            return None

    def get_data_version(self):
        sr = self.data_mountpoint / 'images/strbo-release'
        unmount_needed = False

        try:
            if not self.data_mountpoint_mounted:
                run_command(['mount', str(self.data_mountpoint)])
                unmount_needed = True

            values = _parse_shell_style_file(sr)
            return VersionInfo.from_strbo_release(values)
        except Exception as e:
            errormsg('Failed obtaining recovery data version from {}: {}'
                     .format(sr, e))
            return None
        finally:
            if unmount_needed:
                run_command(['umount', str(self.data_mountpoint)])
