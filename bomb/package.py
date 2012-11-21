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

        if pkg._native:
            self.name = name + '-native'
            self.destdir = Bos.nativedir
            self.indexdir = Bos.nativeindexdir
        else:
            self.name = name
            self.destdir = Bos.targetdir
            self.indexdir = Bos.targetindexdir

        self.baselen = len(pkg._get_stagingdir())
        self.contents = [] #[mode owner size path]


class BosPackage(object):

    def __init__(self, name):

        self.name = name
        if name[-7:] == '-native':
            self._basename = name[:-7]
            self._native = True
        else:
            self._basename = name
            self._native = False

        self.mk = self._get_mk()
        if not self.mk:
            Blog.fatal("unable to find mk for package: %s" % name)
        mk_full_path = os.path.join(Bos.topdir, self.mk)

        Blog.debug('start to parse .mk: %s' % self.mk)
        config = ConfigParser()
        meta = self._preprocess_mk()
        try:
            config.read(meta)
        except ParsingError as e:
            Blog.error(e.message)
            Blog.fatal("failed to parse .mk:  %s <%s>" % (name, self.mk))
        os.remove(meta)

        Blog.debug('parsing package .mk: %s' % self.mk)
        ## package description is required
        try:
            self._description = config.get('BOSMK', 'DESCRIPTION')
        except NoOptionError:
            Blog.fatal("package description missing: %s <%s>" % (name, self.mk))

        ## everything else if optional
        Blog.debug('parsing package .mk: %s optional fields.' % self.mk)
        self.require = []
        self._patch = []
        self._patched = None
        self._src = None
        self._files = {}
        for fld in dict(config.items('BOSMK')):
            if 'require' == fld:
                require = dict(config.items('BOSMK'))[
                    'require'].replace('\n', ' ').split(' ')

                for dep in require:
                    if self._native:
                        if dep[-7:] != '-native':
                            self.require.append(dep + '-native')
                            continue
                    self.require.append(dep)

            elif 'source' == fld:
                sources = dict(config.items('BOSMK'))[
                    'source'].replace('\n', ' ').split(' ')
                for s in sources:
                    if os.path.splitext(s)[1] == '.patch': self._patch.append(s)

                self._src = sources[0]

            elif fld[:5] == 'files':
                self._files.update({fld: dict(config.items('BOSMK'))[fld]})

        ## package misc
        if self._patch: self._patched = os.path.join(Bos.topdir, self._src, '.bos-patch-applied')
        self._mtime = os.path.getmtime(mk_full_path)
        self._gitdir = self._get_gitdir()

        ## installed contents directory:
        ## {package-name: [[mode ownership size path]]}
        self._contents = {}
        ## version info is available only after a successful install.
        self._version = None

        ## put it on shelf
        db = shelve.open(_get_shelf_name(name))
        db['obj'] = self
        db.close()

    @classmethod
    def open(cls, name):

        try:
            db = shelve.open(_get_shelf_name(name))
            pkg = db['obj']
            Blog.debug('package: %s already on shelve' % name)
            if os.path.getmtime(os.path.join(Bos.topdir, pkg.mk)) != pkg._mtime:
                pkg._uninstall()
                pkg = None

        except KeyError: pkg = None

        if not pkg: return BosPackage(name)
        return pkg

    def is_version_diff(self):
        return (False if self._get_version() == self._version else True)


    def prepare(self):

        Blog.info("preparing %s" % self.name)
        self._apply_patch()

        if self.prepare_yes:
            Bos.get_env(self._native)
            return bos_run(['make', '-C', os.path.join(Bos.topdir, self._src),
                            '-f', os.path.join(Bos.mkdir, os.path.basename(self.mk)),
                            '--no-print-directory',
                            'MK=%s' % os.path.dirname(os.path.join(Bos.topdir, self.mk)),
                            'prepare'], self._get_logdir() + '-prepare')
        return (0, None)

    def config(self):

        if self.config_yes:
            Blog.info("configuring %s" % self.name)
            Bos.get_env(self._native)
            return bos_run(['make', '-C', os.path.join(Bos.topdir, self._src),
                            '-f', os.path.join(Bos.mkdir, os.path.basename(self.mk)),
                            '--no-print-directory',
                            'config'], self._get_logdir() + '-config')
        return (0, None)

    def compile(self):

        if self.compile_yes:
            Blog.info("compiling %s" % self.name)
            Bos.get_env(self._native)
            return bos_run(['make', '-C', os.path.join(Bos.topdir, self._src),
                            '-f', os.path.join(Bos.mkdir, os.path.basename(self.mk)),
                            '--no-print-directory',
                            'compile'], self._get_logdir() + '-compile')
        return (0, None)

    def install(self):

        ret = 0
        logname = None
        self._uninstall()
        if self.install_yes:
            Blog.info("installing %s" % self.name)
            if not os.path.exists(self._get_stagingdir()): os.makedirs(self._get_stagingdir())
            ret,logname = bos_run(['make', '-C', os.path.join(Bos.topdir, self._src),
                                   '-f', os.path.join(Bos.mkdir, os.path.basename(self.mk)),
                                   '--no-print-directory',
                                   'DESTDIR=%s' % self._get_stagingdir(),
                                   'install'], self._get_logdir() + '-install')
            if 0 == ret: ret = self._install()
            shutil.rmtree(self._get_stagingdir())

        if 0 == ret:
            ## record package version
            self._version = self._get_version()
            self._flush()
        return (ret, logname)

    def clean(self):

        if self.clean_yes:
            Blog.info("cleaning %s" % self.name)
            Bos.get_env(self._native)
            ret,logname = bos_run(['make', '-C', os.path.join(Bos.topdir, self._src),
                                   '-f', os.path.join(Bos.mkdir, os.path.basename(self.mk)),
                                   '--no-print-directory',
                                   'clean'])
            if 0 != ret: Blog.warn('%s unable to clean' % self.name)
            self._revert_patch()

            if self._gitdir:
                with BosLockFile(os.path.join(Bos.topdir, self._gitdir, '.bos.lock')) as lock:
                    bos_run(['git', '--git-dir=%s' % os.path.join(Bos.topdir, self._gitdir),
                             'clean', '-Xfd'])

            self._uninstall()

            try:
                for fn in glob.glob('%s.?' % (Bos.statesdir + self.name)): os.unlink(fn)
                Bos.touch(Bos.statesdir + self.name + '.v')
            except OSError as e:
                Blog.warn(e.strerror + ': ' + e.filename)

            try:
                shutil.rmtree(os.path.dirname(self._get_logdir()))
            except: pass

        return (0, None)

    def purge(self):

        if self.clean_yes:
            Blog.info("purging %s" % self.name)
            Bos.get_env(self._native)
            ret,logname = bos_run(['make', '-C', os.path.join(Bos.topdir, self._src),
                                   '-f', os.path.join(Bos.mkdir, os.path.basename(self.mk)),
                                   '--no-print-directory',
                                   'clean'])
            if 0 != ret: Blog.warn('%s unable to clean' % self.name)
            self._revert_patch()

            if self._gitdir:
                with BosLockFile(os.path.join(Bos.topdir, self._gitdir, '.bos.lock')) as lock:
                    from subprocess import Popen, PIPE
                    Popen('rm -fr %s/*' % os.path.join(Bos.topdir, self._src),
                          shell = True,
                          stdout = PIPE, stderr = PIPE
                          ).communicate()
                    Popen('cd %s/.. && git reset --hard' % os.path.join(Bos.topdir, self._gitdir),
                          shell = True,
                          stdout = PIPE, stderr = PIPE
                          ).communicate()

            self._purge()

            try:
                for fn in glob.glob('%s.?' % (Bos.statesdir + self.name)): os.unlink(fn)
                Bos.touch(Bos.statesdir + self.name + '.v')
            except OSError as e:
                Blog.warn(e.strerror + ': ' + e.filename)

            try:
                shutil.rmtree(os.path.dirname(self._get_logdir()))
            except: pass

        return (0, None)

    def dump(self):

        print '-' * 80
        print '%-12s: %s' % ('NAME', self.name)
        print '%-12s: %s' % ('DESCRIPTION', '\n\t'.join(self._description.split('\n')))
        print '-' * 80
        print '%-12s: %s' % ('MK', os.path.join(Bos.topdir, self.mk))
        print '%-12s: %s' % ('SRC', os.path.join(Bos.topdir, self._src))
        if self.require: print '%-12s: %s' % ('DEPEND', ' '.join(self.require))
        print '-' * 80

        if self._contents:
            for k, v in self._contents.items():
                print '\n%s:' % k
                for i in v:
                    print '\t%s %s %10s %s' % (i[0], i[1], i[2], i[3])

        print

    def _put_info(self, info):

        self._contents.update(info)

    def _flush(self):

        db = shelve.open(_get_shelf_name(self.name))
        db['obj'] = self
        db.close()

    def _install(self):
        """
        install package from staging area to output area and populate DB

        examine contents in staging area to make sure that,
        - all package specified contents must exist, unless optional
        - all installed contents must associate with given package

        return: 0 if successful, error code otherwise
        """

        ## walk through package and sub-package definitions if any
        for kn in self._files:
            if kn == 'files':
                pn = self._basename
            else:
                pn = self._basename + kn[5:]

                Blog.debug('processing package: %s' % pn)

            ctx = BosInstallContext(pn, self)
            try:
                for itm in self._files[kn].split('\n'):
                    if '' == itm.strip(): continue

                    ownership, pattern, optional = _parse_install_item(itm)

                    Blog.debug('processing pattern: %s' % pattern)
                    flist = glob.glob(os.path.join(self._get_stagingdir(), pattern[1:]))
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
                self._put_info({ctx.name:ctx.contents})
                self._uninstall()
                return -1

            Blog.debug('%s writing package info' % ctx.name)
            self._put_info({ctx.name:ctx.contents})

        ## post process: walk the stagingdir to make sure there's no files left
        try:
            for r, d, f in os.walk(self._get_stagingdir()):
                if f: Blog.fatal('installed but unpackaged contents found: %s\n%s'
                                 % (self.name, _list_dir(self._get_stagingdir())))
        except:
            Blog.error('%s unable to walk staging dir: %s'
                       % (self.name, self._get_stagingdir()))
            self._uninstall()
            return -2

        return 0

    def _uninstall(self):
        """
        uninstall package both from output and index DB area

        uninstall also checks to remove any path that becomes empty
        due to this package's uninstallation.
        """
        try:
            ## must acquire the global lock
            lockdir = Bos.nativedirlock if self._native else Bos.targetdirlock

            with BosLockFile(lockdir) as lock:
                ## clean up output and index area based on cached package info
                for pn in self._contents:
                    for lst in self._contents[pn]:
                        fn = lst[3]
                        Blog.debug('%s removing %s' % (self.name, fn[1:]))
                        if self._native:
                            os.unlink(os.path.join(Bos.nativedir, fn[1:]))
                            os.unlink(os.path.join(Bos.nativeindexdir, fn[1:]))
                        else:
                            os.unlink(os.path.join(Bos.targetdir, fn[1:]))
                            os.unlink(os.path.join(Bos.targetindexdir, fn[1:]))

                ## check output area to remove left-over empty paths
                for kn in self._files:
                    for itm in self._files[kn].split('\n'):
                        if not itm.strip(): continue
                        dn = os.path.dirname(itm)
                        Blog.debug('package %s removing item: %s' % (self.name, dn))
                        if dn and  '/' != dn:
                            if self._native:
                                bos_rm_empty_path(dn, Bos.nativedir)
                                bos_rm_empty_path(dn, Bos.nativeindexdir)
                            else:
                                bos_rm_empty_path(dn, Bos.targetdir)
                                bos_rm_empty_path(dn, Bos.targetindexdir)

        except: ## all uninstall errors are ignored
            Blog.debug('%s unable to uninstall.' % self.name)

        self._contents = {}
        self._version = None
        self._flush()

    def _purge(self):
        """
        uninstall package and remove dangling index if any.
        """

        self._uninstall()

        for r,d,f in os.walk(
            Bos.nativeindexdir if self._native else Bos.targetindexdir):
            for fn in f:
                if (self.name == os.readlink(os.path.join(r, fn))):
                    os.unlink(os.path.join(r, fn))

    def _apply_patch(self):
        """
        apply package patches if available.
        """

        ret = 0
        if self._patch and not os.path.exists(self._patched):
            for p in self._patch:
                Blog.debug("patching %s: %s" % (self.name, p))
                ret,logname = bos_run(
                    ['patch', '-p1',
                     '-d', os.path.join(Bos.topdir, self._src),
                     '-i', os.path.join(Bos.topdir, os.path.dirname(self.mk), p)])
                if 0 != ret:
                    Blog.fatal('%s unable to apply patch: %s' % (self.name, p))

        if 0 == ret and self._patch:
            Bos.touch(self._patched)

    def _revert_patch(self):
        """
        revert package patches if available.
        """
        if self._patch and os.path.exists(self._patched):
            for p in reversed(self._patch):
                Blog.debug("reverting %s: %s" % (self.name, p))

                ret,logname = bos_run(
                    ['patch', '-Rp1',
                     '-d', os.path.join(Bos.topdir, self._src),
                     '-i', os.path.join(Bos.topdir, os.path.dirname(self.mk), p)])
                if 0 != ret:
                    Blog.fatal('%s unable to revert patch: %s' % (self.name, p))
            os.unlink(self._patched)

    def _get_mk(self):
        Blog.debug("get mkpath for: %s" % self.name)

        mkpath = self._do_get_mk(Bos.distrodir)
        if not mkpath: mkpath = self._do_get_mk(Bos.topdir)

        Blog.debug("mk for: %s as: %s" % (self.name, mkpath))
        if mkpath: return(mkpath[len(Bos.topdir):])
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
                        return os.path.join(r, fn)
                    if True == self._native:
                        if fn == '%s.mk' % self._basename:
                            mk = fn
                            path = r

        return None if not mk else os.path.join(path, mk)

    def _preprocess_mk(self):
        import re
        mk_full_path = os.path.join(Bos.topdir, self.mk)
        meta = mk_full_path + '.meta'
        real = os.path.join(Bos.mkdir, os.path.basename(self.mk))

        self.prepare_yes = False
        self.config_yes = False
        self.compile_yes = False
        self.install_yes = False
        self.clean_yes = False

        r = open(real, "w")
        try:
            r.write('## AUTOGENERATED FILE - DO NOT MODIFY\n')
            r.write('.PHONY: prepare config compile install clean\n')

            with open(meta, "w") as m:
                m.write('[BOSMK]\n')
                for line in open(mk_full_path):
                    if line[:3] == '## ': m.write(line[3:])
                    else:
                        if re.match(r'^\s*$', line): continue
                        else : r.write(line)

                        if re.match(r'^\w+', line) :
                            if re.match(r'.*\bprepare\b', line):
                                self.prepare_yes = True
                            if re.match(r'.*\bconfig\b', line):
                                self.config_yes = True
                            if re.match(r'.*\bcompile\b', line):
                                self.compile_yes = True
                            if re.match(r'.*\binstall\b', line):
                                self.install_yes = True
                            if re.match(r'.*\bclean\b', line):
                                self.clean_yes = True

        finally:
            r.close()

        return meta


    def _get_stagingdir(self):
        return os.path.join(Bos.cachedir, self.name)


    def _get_logdir(self):
        return os.path.join(Bos.logdir, self._basename,
                            'native' if self._native else 'target')

    def _get_gitdir(self):
        gitdir = None
        if self._src:
            from subprocess import Popen, PIPE
            out, err = Popen('cd %s; git rev-parse --show-toplevel'
                             % os.path.join(Bos.topdir, self._src), shell = True,
                             stdout = PIPE, stderr = PIPE
                             ).communicate()
            if err: Blog.warn('%s: not a git repository.' % os.path.join(Bos.topdir, self._src))
            else: gitdir = os.path.join(out.strip(), '.git')[len(Bos.topdir):]
        return gitdir

    def _get_version(self):

        version = 'unknown'
        if self._gitdir:
            from subprocess import Popen, PIPE
            out,err = Popen('cd %s; git describe --all'
                            % os.path.join(Bos.topdir, self._gitdir), shell = True,
                            stdout = PIPE, stderr = PIPE).communicate()
            if not err: version = out.strip()

        return version


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
        lockdir = Bos.nativedirlock if context.pkg._native else Bos.targetdirlock
        with BosLockFile(lockdir) as lock:

            path = os.path.join(context.destdir, os.path.dirname(rel_src))
            if not os.path.exists(path): os.makedirs(path)

            Blog.debug('installing from: %s to %s' % (src, path))
            try:
                shutil.move(src, path + '/')
            except shutil.Error:
                owner = _who_has(rel_src, context.pkg._native)
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
