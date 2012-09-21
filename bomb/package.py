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

import os, sys, glob, shutil
import shelve
from ConfigParser import ConfigParser, NoOptionError, ParsingError

from bomb.main import Bos
from bomb.log import Blog
from bomb.util import bos_run, bos_rm_empty_path, bos_fileinfo
from bomb.lockfile import BosLockFile

class BosInstallContext(object):

    def __init__(self, name, pkg):

        self.pkg = pkg

        if pkg.native:
            self.name = name + '-native'
            self.destdir = Bos.nativedir
            self.indexdir = Bos.nativeindexdir
        else:
            self.name = name
            self.destdir = Bos.targetdir
            self.indexdir = Bos.targetindexdir

        self.baselen = len(pkg.stagingdir)
        self.contents = [] #[mode owner size path]


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
        try:
            config.read(tmp_mk)
        except ParsingError as e:
            Blog.error(e.message)
            Blog.fatal("failed to parse .mk:  %s <%s>" % (name, self.mk))

        os.remove(tmp_mk)

        ## package description is required
        try:
            self.description = config.get('BOSMK', 'DESCRIPTION')
        except NoOptionError:
            Blog.fatal("package description missing: %s <%s>" % (name, self.mk))

        ## everything else if optional
        self.require = []
        self.patch = []
        self.patched = None
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
                sources = dict(config.items('BOSMK'))[
                    'source'].replace('\n', ' ').split(' ')
                for s in sources:
                    if os.path.splitext(s)[1] == '.patch': self.patch.append(s)

                self.src = os.path.join(Bos.topdir, sources[0])

            elif fld[:5] == 'files':
                self.files.update({fld: dict(config.items('BOSMK'))[fld]})

        ## package misc
        if self.patch: self.patched = os.path.join(self.src, '.bos-patch-applied')
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

        ## info directory:
        ## {package-name: [[mode ownership size path]]}
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

    def install(self):
        """
        install package from staging area to output area and populate DB

        examine contents in staging area to make sure that,
        - all package specified contents must exist, unless optional
        - all installed contents must associate with given package

        return: 0 if successful, error code otherwise
        """

        ## walk through package and sub-package definitions if any
        for kn in self.files:
            if kn == 'files':
                pn = self.basename
            else:
                pn = self.basename + kn[5:]

                Blog.debug('processing package: %s' % pn)

            ctx = BosInstallContext(pn, self)
            try:
                for itm in self.files[kn].split('\n'):
                    if '' == itm.strip(): continue

                    ownership, pattern, optional = _parse_install_item(itm)

                    Blog.debug('processing pattern: %s' % pattern)
                    flist = glob.glob(os.path.join(self.stagingdir, pattern[1:]))
                    if (not flist) and (not optional):
                        Blog.fatal('<%s> unable to find: %s' % (self.name,  pattern))
                    for ff in flist: _install_files(ff, ownership, ctx)

                for ctnt in ctx.contents:
                    ff = ctnt[3]
                    path = os.path.join(ctx.indexdir, ff[1:])
                    if not os.path.exists(os.path.dirname(path)):
                        os.makedirs(os.path.dirname(path))
                    #with open(path, 'w') as f: f.write(ctx.name)
                    os.symlink(ctx.name, path)
            except:
                Blog.error("%s unable to install." % self.name)
                self.put_info({ctx.name:ctx.contents})
                self.uninstall()
                return -1

            Blog.debug('%s writing package info' % ctx.name)
            self.put_info({ctx.name:ctx.contents})

        ## post process: walk the stagingdir to make sure there's no files left
        try:
            for r, d, f in os.walk(self.stagingdir):
                if f: Blog.fatal('installed but unpackaged contents found: %s\n%s'
                                 % (self.name, _list_dir(self.stagingdir)))
        except:
            Blog.error('%s unable to walk staging dir: %s'
                       % (self.name, self.stagingdir))
            self.uninstall()
            return -2

        self.flush()

        return 0

    def uninstall(self):
        """
        uninstall package both from output and index DB area

        uninstall also checks to remove any path that becomes empty
        due to this package's uninstallation.
        """
        try:
            ## must acquire the global lock
            lockdir = Bos.nativedirlock if self.native else Bos.targetdirlock

            with BosLockFile(lockdir) as lock:
                ## clean up output and index area based on cached package info
                for pn in self.info:
                    for lst in self.info[pn]:
                        fn = lst[3]
                        Blog.debug('%s removing %s' % (self.name, fn[1:]))
                        if self.native:
                            os.unlink(os.path.join(Bos.nativedir, fn[1:]))
                            os.unlink(os.path.join(Bos.nativeindexdir, fn[1:]))
                        else:
                            os.unlink(os.path.join(Bos.targetdir, fn[1:]))
                            os.unlink(os.path.join(Bos.targetindexdir, fn[1:]))

                ## check output area to remove left-over empty paths
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

        except: ## all uninstall errors are ignored
            Blog.debug('%s unable to uninstall.' % self.name)

        self.info = {}
        self.flush()

    def purge(self):
        """
        uninstall package and remove dangling index if any.
        """

        self.uninstall()

        for r,d,f in os.walk(
            Bos.nativeindexdir if self.native else Bos.targetindexdir):
            for fn in f:
                if (self.name == os.readlink(os.path.join(r, fn))):
                    os.unlink(os.path.join(r, fn))

    def apply_patch(self):
        """
        apply package patches if available.
        """

        ret = 0
        if self.patch and not os.path.exists(self.patched):
            for p in self.patch:
                Blog.debug("patching %s: %s" % (self.name, p))
                ret,logname = bos_run(
                    ['patch', '-p1',
                     '-d', self.src,
                     '-i', os.path.join(os.path.dirname(self.mk), p)])
                if 0 != ret:
                    Blog.fatal('%s unable to apply patch: %s' % (self.name, p))

        if 0 == ret and self.patch:
            Bos.touch(self.patched)

    def revert_patch(self):
        """
        revert package patches if available.
        """
        if self.patch and os.path.exists(self.patched):
            for p in reversed(self.patch):
                Blog.debug("reverting %s: %s" % (self.name, p))
                ret,logname = bos_run(
                    ['patch', '-Rp1',
                     '-d', self.src,
                     '-i', os.path.join(os.path.dirname(self.mk), p)])
                if 0 != ret:
                    Blog.fatal('%s unable to revert patch: %s' % (self.name, p))
            os.unlink(self.patched)

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
                    Blog.debug('mk found as: %s at %s' % (fn, r))
                    if fn == '%s.mk' % self.name:
                        return os.path.join(path, fn)
                    if True == self.native:
                        if fn == '%s.mk' % self.basename:
                            mk = fn
                            path = r

        return None if not mk else os.path.join(path, mk)

    def _gen_tmp_mk(self):
        import re

        tmpmk = self.mk + '.tmp'

        self.prepare_yes = False
        self.config_yes = False
        self.compile_yes = False
        self.install_yes = False
        self.clean_yes = False

        with open(tmpmk, "w") as f:
            f.write('[BOSMK]\n')
            for line in open(self.mk):
                if line[:3] == '## ': f.write(line[3:])
                else:
                    if re.match('^[\w\s]*prepare[\w\s]*:', line):
                        self.prepare_yes = True
                    if re.match('^[\w\s]*config[\w\s]*:', line):
                        self.config_yes = True
                    if re.match('^[\w\s]*compile[\w\s]*:', line):
                        self.compile_yes = True
                    if re.match('^[\w\s]*install[\w\s]*:', line):
                        self.install_yes = True
                    if re.match('^[\w\s]*clean[\w\s]*:', line):
                        self.clean_yes = True

        return tmpmk


def _get_shelf_name(name):
    """return shelf path for package with given name."""

    return os.path.join(Bos.shelvedir, name)

def _install_files(src, ownership, context):

    if os.path.isdir(src):
        for ff in os.listdir(src):
            Blog.debug('installing: %s' % ff)
            _install_files(os.path.join(src, ff), ownership, context)
    else:
        rel_src = src[context.baselen:]
        if rel_src[0] == '/': rel_src = rel_src[1:]

        mode, size = bos_fileinfo(src)

        ## actual install must acquire the global lock
        lockdir = Bos.nativedirlock if context.pkg.native else Bos.targetdirlock
        with BosLockFile(lockdir) as lock:

            path = os.path.join(context.destdir, os.path.dirname(rel_src))
            if not os.path.exists(path): os.makedirs(path)

            Blog.debug('installing from: %s to %s' % (src, path))
            try:
                shutil.move(src, path + '/')
            except shutil.Error:
                owner = _who_has(rel_src, context.pkg.native)
                if owner == context.name:
                    os.unlink(path, os.path.basename(src))
                    shutil.move(src, path + '/')
                else:
                    Blog.fatal('package %s conflicts with: %s\n%s'
                               % (context.name, owner, rel_src))

        info = []
        ## if file is no longer in src, it must be in destdir already
        if '----------' == mode:
            mode, size = bos_fileinfo(os.path.join(context.destdir, rel_src))
        info.append(mode)
        info.append(ownership if ownership else 'root:root')
        info.append(size)
        info.append('/' + rel_src)

        context.contents.append(info)


def _parse_install_item(item):

    ownership = None
    optional = False

    patterns = item.split()

    num = len(patterns)
    if num == 1: pattern = patterns[0]

    elif num == 2:
        if patterns[0][0] == '/':
            pattern = patterns[0]
            optional = True
        else:
            ownership = patterns[0]
            pattern = patterns[1]

    elif num == 3:
        ownership = patterns[0]
        pattern = patterns[1]
        optional = True

    return (ownership, pattern, optional)


def _list_dir(dirname):

    dirlen = len(dirname)
    files = []
    for r, d, f in os.walk(dirname):
        for fn in f:
            base_r = r[dirlen:]
            files.append(os.path.join(base_r if base_r else '/', fn))
    return '\n'.join(files)


def _who_has(content, native = False):

    path = os.path.join(Bos.nativeindexdir if native else Bos.targetindexdir, content)
    try:
        #owner = open(path).read()
        owner = os.readlink(path)
    except:
        owner = None

    return owner
