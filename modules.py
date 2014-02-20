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

""" Parses the modules.xml file """

from xml.etree.ElementTree import ElementTree

class ModulesItem(object):
    """ Represents a project in the modules.xml file """
    def __init__(self):
        self.name = None
        self.pkgname = None
        self.pkgconfig = None
        self.wait_repo = False
        self.disabled = False
        self.autobuild = True
        self.release_glob = {}
        self.deps = []
        self.depsolve_level = 0

        # add the default gnome release numbers
        self.release_glob['f18'] = "3.6.*"
        self.release_glob['f19'] = "3.8.*"
        self.release_glob['f20'] = "3.9.*,3.10.*,3.10"
        self.release_glob['rawhide'] = "*"

class ModulesXml(object):
    """ Parses the modules.xml file """

    def __init__(self, filename):
        self.items = []
        tree = ElementTree()
        tree.parse(filename)
        projects = list(tree.iter("project"))
        for project in projects:
            item = ModulesItem()
            item.disabled = False
            item.name = project.get('name')
            item.pkgname = project.get('pkgname')
            if not item.pkgname:
                item.pkgname = item.name
            item.pkgconfig = project.get('pkgconfig')
            if not item.pkgconfig:
                item.pkgconfig = item.name
            if project.get('wait_repo') == "1":
                item.wait_repo = True
            if project.get('autobuild') == "False":
                item.autobuild = False
            if project.get('disabled') == "True":
                item.disabled = True
            for data in project:
                if data.tag == 'dep':
                    item.deps.append(data.text)
                elif data.tag == 'release':
                    version = data.get('version')
                    item.release_glob[version] = data.text
            self.items.append(item)

    def depsolve(self):
        """ depsolves the list into the correct order """

        # check there are no recyprical deps
        for item in self.items:
            for dep in item.deps:
                item2 = self._get_item_by_name(dep)
                if not item2:
                    continue
                if item.pkgname in item2.deps:
                    print item.pkgname, "depends on", item2.pkgname
                    print item2.pkgname, "depends on", item.pkgname
                    return False

        # do the depsolve
        changes = True
        cnt = 0
        while changes:
            if cnt > 10000:
                print "Depsolve error"
                self.items = sorted(self.items, key=lambda item: item.depsolve_level)
                for item in self.items:
                    if item.name:
                        print item.name, item.depsolve_level
                    else:
                        print item.pkgname, item.depsolve_level
                    for dep in item.deps:
                        print "  ", dep, self._get_item_by_name(dep).depsolve_level
                return False
            changes = False
            for item in self.items:
                for dep in item.deps:
                    item_dep = self._get_item_by_name(dep)
                    if not item_dep:
                        print "failed to find dep", dep
                        return False
                    if item.depsolve_level <= item_dep.depsolve_level:
                        item.depsolve_level += 1
                        changes = True
                        cnt = cnt + 1
                        break
                if changes:
                    break
        # sort by depsolve key
        self.items = sorted(self.items, key=lambda item: item.depsolve_level)
        return True

    def _print(self):
        for item in self.items:
            print("%02i " % item.depsolve_level + ' ' * item.depsolve_level + item.pkgname)

    def _get_item_by_name(self, name):
        for item in self.items:
            if item.name == name:
                return item
        return None
