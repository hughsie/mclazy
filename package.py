#!/usr/bin/python
# Licensed under the GNU General Public License Version 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# Copyright (C) 2014
#    Richard Hughes <richard@hughsie.com>

""" A package with NVR data """

import rpm
import os

class Package(object):
    """ A package with NVR data """

    def __init__(self, filename=None):
        self.url = None
        self.epoch = None
        if filename:
            fd = os.open(filename, os.O_RDONLY)
            ts = rpm.TransactionSet()
            h = ts.hdrFromFdno(fd)
            os.close(fd)
            self.name = h['name']
            self.version = h['version']
            self.release = h['release']
        else:
            self.name = None
            self.version = None
            self.release = None

    def get_url(self):
        """ Returns the full URL of the source package """
        if self.url:
            return self.url
        self.url = 'http://kojipkgs.fedoraproject.org/packages/'
        self.url += "%s/%s/%s/src/" % (self.name, self.version, self.release)
        self.url += "%s-%s-%s.src.rpm" % (self.name, self.version, self.release)
        return self.url

    def get_nvr(self):
        """ Returns the NVR of the package """
        return "%s-%s-%s" % (self.name, self.version, self.release)
    def get_evr(self):
        """ Returns the NVR of the package """
        return (self.epoch, self.version, self.release)
