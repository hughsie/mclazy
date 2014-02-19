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

from xml.etree.ElementTree import ElementTree

class ModulesItem:
    def __init__(self):
        self.name = None
        self.pkgname = None
        self.wait_repo = False
        self.disabled = False
        self.release_glob = {}
        self.deps = []
        self._depsolve_order = 0;

        # add the default gnome release numbers
        self.release_glob['f18'] = "3.6.*"
        self.release_glob['f19'] = "3.8.*"
        self.release_glob['f20'] = "3.9.*,3.10.*,3.10"
        self.release_glob['rawhide'] = "*"

class ModulesXml:
    def __init__(self, filename):
        self.items = []
        tree = ElementTree()
        tree.parse(filename)
        projects = list(tree.iter("project"))
        for project in projects:
            item = ModulesItem()
            item.name = project.get('name')
            item.pkgname = project.get('pkgname')
            if not item.pkgname:
                item.pkgname = item.name;
            if project.get('wait_repo') == "1":
                item.wait_repo = True;
            if project.get('disabled') == "1":
                item.disabled = True;
            for data in project:
                if data.tag == 'dep':
                    item.deps.append(data.text)
                elif data.tag == 'release':
                    version = data.get('version')
                    item.release_glob[version] = data.text
            self.items.append(item)

    def depsolve(self):

        # check there are no recyprical deps
        for item in self.items:
            for dep in item.deps:
                item2 = self._get_item_by_name(dep)
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
                self.items = sorted(self.items, key=lambda item: item._depsolve_order)
                for item in self.items:
                    if item.name:
                        print item.name, item._depsolve_order
                    else:
                        print item.pkgname, item._depsolve_order
                    for dep in item.deps:
                        print "  ", dep, self._get_item_by_name(dep)._depsolve_order
                return False
            changes = False
            for item in self.items:
                for dep in item.deps:
                    item_dep = self._get_item_by_name(dep)
                    if not item_dep:
                        print "failed to find dep", dep
                        return False
                    if item._depsolve_order <= item_dep._depsolve_order:
                        item._depsolve_order += 1
                        changes = True
                        cnt = cnt + 1
                        break
                if changes:
                    break
        # sort by depsolve key
        self.items = sorted(self.items, key=lambda item: item._depsolve_order)
        return True

    def _print(self):
        for item in self.items:
            print("%02i " % item._depsolve_order + ' ' * item._depsolve_order + item.pkgname)

    def _get_item_by_name(self, name):
        for item in self.items:
            name_tmp = item.name
            if not name_tmp:
                name_tmp = item.pkgname
            if name_tmp == name:
                return item
        return None

    def get_pkgnames(self):
        pkg_names = []
        for item in self.items:
            if item.disabled:
                continue
            pkg_names.append(item.pkgname)
        return pkg_names
