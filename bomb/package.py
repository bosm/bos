# Copyright (C) 2012        SWOAG Technology
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os, sys
import shelve
from ConfigParser import ConfigParser, NoOptionError

from bomb.main import Bos
from bomb.log import Blog
from bomb.util import bos_run, bos_rm_empty_path

class BosPackage(object):

    def __init__(self, name):

        self.name = name
        if name[-7:] == '-native':
            self.basename = name[:-7]
            self.native = True
        else:
            self.basename = name
            self.native = False

        self.mk = self._get_mk()
        if not self.mk:
            Blog.fatal("unable to find mk for package: %s" % name)

        config = ConfigParser()
        tmp_mk = self._gen_tmp_mk()
        config.read(tmp_mk)
        os.remove(tmp_mk)

        ## package description is required
        try:
            self.description = config.get('BOSMK', 'DESCRIPTION')
        except NoOptionError:
            Blog.fatal("package description missing: %s <%s>" % (name, self.mk))

        ## everything else if optional
        self.require = []
        self.src = None
        self.files = {}
        for fld in dict(config.items('BOSMK')):
            if 'require' == fld:
                require = dict(config.items('BOSMK'))[
                    'require'].replace('\n', ' ').split(' ')

                for dep in require:
                    if self.native:
                        if dep[-7:] != '-native':
                            self.require.append(dep + '-native')
                            continue
                    self.require.append(dep)

            elif 'source' == fld:
                self.src = os.path.join(
                    Bos.topdir, dict(config.items('BOSMK'))['source'])

            elif fld[:5] == 'files':
                self.files.update({fld: dict(config.items('BOSMK'))[fld]})

        ## package misc
        self.mtime = os.path.getmtime(self.mk)
        self.stagingdir = os.path.join(Bos.cachedir, name)
        self.logdir = os.path.join(Bos.logdir, self.basename,
                                   'native' if self.native else 'target')

        self.gitdir = None
        if self.src:
            from subprocess import Popen, PIPE
            out, err = Popen('cd %s; git rev-parse --show-toplevel'
                             % self.src, shell = True,
                             stdout = PIPE, stderr = PIPE
                             ).communicate()
            if err: Blog.warn('%s: not a git repository.' % self.src)
            else: self.gitdir = os.path.join(out.strip(), '.git')

        self.info = {}

        ## put it on shelf
        db = shelve.open(_get_shelf_name(name))
        db['obj'] = self
        db.close()

    def put_info(self, info):

        self.info.update(info)

    def flush(self):

        db = shelve.open(_get_shelf_name(self.name))
        db['obj'] = self
        db.close()

    def uninstall(self):

        for pn in self.info:
            for fn in self.info[pn]:
                if self.native:
                    os.unlink(os.path.join(Bos.nativedir, fn[1:]))
                    os.unlink(os.path.join(Bos.nativeindexdir, fn[1:]))
                else:
                    os.unlink(os.path.join(Bos.targetdir, fn[1:]))
                    os.unlink(os.path.join(Bos.targetindexdir, fn[1:]))

        for kn in self.files:
            for itm in self.files[kn].split('\n'):
                if not itm.strip(): continue
                dn = os.path.dirname(itm)
                Blog.debug('package %s removing item: %s' % (self.name, dn))
                if dn and  '/' != dn:
                    if self.native:
                        bos_rm_empty_path(dn, Bos.nativedir)
                        bos_rm_empty_path(dn, Bos.nativeindexdir)
                    else:
                        bos_rm_empty_path(dn, Bos.targetdir)
                        bos_rm_empty_path(dn, Bos.targetindexdir)

        self.info = {}
        self.flush()

    @classmethod
    def open(cls, name):

        try:
            db = shelve.open(_get_shelf_name(name))
            Blog.debug('package: %s already on shelve' % name)
            pkg = db['obj']
            if os.path.getmtime(pkg.mk) != pkg.mtime:
                pkg.uninstall()
                pkg = None

        except KeyError: pkg = None

        if not pkg: return BosPackage(name)
        return pkg

    def _get_mk(self):
        Blog.debug("get mkpath for: %s" % self.name)

        mkpath = self._do_get_mk(Bos.distrodir)
        if not mkpath: mkpath = self._do_get_mk(Bos.topdir)

        Blog.debug("mk for: %s as: %s" % (self.name, mkpath))
        return mkpath

    def _do_get_mk(self, root):
        Blog.debug('search mk at: %s for %s' % (root, self.name))

        mk = None
        path = None
        for r,d,f in os.walk(os.path.join(root, 'bm')):
            for fn in f:
                if fn.endswith('.mk'):
                    path = r
                    if fn == '%s.mk' % self.name:
                        return os.path.join(path, fn)
                    if True == self.native:
                        if fn == '%s.mk' % self.basename: mk = fn

        return None if not mk else os.path.join(path, mk)

    def _gen_tmp_mk(self):
        import re

        tmpmk = self.mk + '.tmp'

        self.prepare = False
        self.config = False
        self.compile = False
        self.install = False
        self.clean = False

        with open(tmpmk, "w") as f:
            f.write('[BOSMK]\n')
            for line in open(self.mk):
                if line[:3] == '## ': f.write(line[3:])
                else:
                    if re.match('^[\w\s]*prepare[\w\s]*:', line): self.prepare = True
                    if re.match('^[\w\s]*config[\w\s]*:', line): self.config = True
                    if re.match('^[\w\s]*compile[\w\s]*:', line): self.compile = True
                    if re.match('^[\w\s]*install[\w\s]*:', line): self.install = True
                    if re.match('^[\w\s]*clean[\w\s]*:', line): self.clean = True

        return tmpmk


def _get_shelf_name(name):
    """return shelf path for package with given name."""

    return os.path.join(Bos.shelvedir, name)
