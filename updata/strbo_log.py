#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2020, 2021  T+A elektroakustik GmbH & Co. KG
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

import logging
import logging.handlers


def _create_syslog_handler():
    h = logging.handlers.SysLogHandler(address='/dev/log')
    f = logging.Formatter('%(name)s: %(message)s')
    h.setFormatter(f)
    return h


_log = logging.getLogger('updaTA')
_log.addHandler(_create_syslog_handler())
_log.addHandler(logging.StreamHandler())
_log.setLevel(logging.INFO)


def errormsg(msg):
    _log.error('ERROR: ' + msg)


def log(msg):
    _log.info(msg)


if __name__ == '__main__':
    pass
