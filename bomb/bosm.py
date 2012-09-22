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

import os, sys, shutil
from subprocess import call

from bomb.main import Bos
from bomb.log import Blog


def bosm(args):

    args.target = _fuzzy_target(args.target)

    ## cleanup all existing logs
    if 'clean' in args.target:
        try: shutil.rmtree(Bos.logdir)
        except: pass


    ## BOS internal environments required by logging system.
    os.environ['_BOS_DEBUG_'] = 'yes' if args.debug == True else 'no'
    os.environ['_BOS_TRACE_'] = 'yes' if args.trace == True else 'no'
    os.environ['_BOS_VERBOSE_'] = 'yes' if args.verbose == True else 'no'


    ### bootstrap build system
    Bos.setup()
    Blog.debug("entering to build system, topdir: %s" % Bos.topdir)


    if _bootstrapcheck():
        Blog.debug("bootstrap required.")
        Bos.touch(os.path.join(Bos.cachedir, '.rebootstrap'))
        Bos.touch(os.path.join(Bos.cachedir, '.rebuild'))

    ret = 0
    if not 'bootstrap' in args.target:
        Blog.debug("checking to bootstrap ...")
        ret = call(['make', '-C', Bos.cachedir,
                    '-f', Bos.topdir + 'bos/mk/bootstrap.mk',
                    '--no-print-directory'])
        if 0 != ret: Blog.fatal('unable to bootstrap')

    ## from this point on, build system is bootstraped and ready:
    ## - all envorinments are in place and ready to consume build target
    if 'info' in args.target: _print_info()

    if 0 == ret:
        Blog.debug("top-level make ...")
        for target in args.target:
            if target[-5:] == '-info': _print_pkg_info(target[:-5])

            call(['make', '-C', Bos.cachedir,
                  '-f', Bos.topdir + 'bos/mk/main.mk',
                  '-j' + str(args.jobs) if args.jobs else '-j',
                  '--no-print-directory', target])

    print ''
    print 'build summary at: {0}'.format(Blog.name())


def _ambiguous_target(target, match):

    print
    print 'ambiguous target: %s' % target
    print '\t' + '\n\t'.join(match)
    print
    sys.exit(-1)


def _fuzzy_target(target):

    target_real = []

    pkgs_all = []
    builtins = ['prepare', 'config', 'compile', 'install', 'clean', 'purge', 'info']

    pkgs = _all_pkgs()

    pkgs_all.extend(pkgs)
    pkgs_all.extend(['all', 'clean', 'info'])

    match = []
    for t in target:
        ## look for exact match first
        if t in pkgs_all:
            target_real.append(t)
            continue

        ## auto complete: with package itself
        for p in pkgs_all:
            if p.startswith(t):
                match.append(p)

        if len(match) == 1:
            target_real.append(match[0])
            continue
        elif len(match) > 1:
            _ambiguous_target(t, match)

        ## auto complete: with package actions
        for p in pkgs:
            for bis in builtins:
                pp = '-'.join([p, bis])
                if pp.startswith(t):
                    match.append(pp)

        if len(match) == 1:
            target_real.append(match[0])
            continue
        elif len(match) > 1:
            _ambiguous_target(t, match)

        ## fuzzy matching: the order is important, so that the closer match is
        ## picked up the first.

        ## detect action as prefix/suffix
        for bis in builtins:
            pp = None
            if t.startswith(bis + '-'):
                pp = t[len(bis) + 1:]
            if t.endswith('-' + bis):
                pp = t[:-len(bis) - 1]

            if pp:
                for p in pkgs:
                    if p.startswith(pp):
                        match.append('-'.join([p, bis]))

        if len(match) == 1:
            target_real.append(match[0])
            continue
        elif len(match) > 1:
            _ambiguous_target(t, match)


        ## detect action as fuzzy prefix/suffix
        for bis in builtins:
            pp = None
            tsp = t.split('-')
            if bis.startswith(tsp[0]):
                pp = t[len(tsp[0]) + 1:]
            elif bis.startswith(tsp[-1]):
                pp = t[:-len(tsp[-1]) - 1]

            if pp:
                for p in pkgs:
                    if p.startswith(pp):
                        match.append('-'.join([p, bis]))

        if len(match) == 1:
            target_real.append(match[0])
            continue
        elif len(match) > 1:
            _ambiguous_target(t, match)

        else:
            print ('\ninvalid build target: %s\n' % t)
            sys.exit(-1)


    return target_real


def _all_pkgs():

    pkgs = []
    try: pkgs.extend(open(os.path.join(Bos.cachedir, 'toolchain-packages'))
                     .read().strip().split('\n'))
    except: pass

    try: pkgs.extend(open(os.path.join(Bos.cachedir, 'packages'))
                     .read().strip().split('\n'))
    except: pass
    return pkgs


def _bootstrapcheck():

        if not os.path.exists(os.path.join(Bos.cachedir, '.bootstrap')):
            return True
        if open(os.path.join(Bos.cachedir, '.bootstrap'),'r').read() != Bos.topdir:
            return True
        return False


def _print_info():

    print '\nall buidable packages:\n%s' % ('-' * 80)

    pkgs = _all_pkgs()

    pkgs.sort()
    if len(pkgs) % 2 != 0: pkgs.append(' ')
    split = len(pkgs) / 2
    l1 = pkgs[0:split]
    l2 = pkgs[split:]
    for key, value in zip(l1, l2): print '%-40s %s' % (key, value)

    print
    sys.exit(0)


def _print_pkg_info(name):

    from bomb.package import BosPackage

    try: pkg = BosPackage.open(name)
    except: pass

    print '-' * 80
    print '%-12s: %s' % ('NAME', pkg.name)
    print '%-12s: %s' % ('DESCRIPTION', '\n\t'.join(pkg.description.split('\n')))
    print '-' * 80
    print '%-12s: %s' % ('MK', pkg.mk)
    print '%-12s: %s' % ('SRC', pkg.src)
    if pkg.require: print '%-12s: %s' % ('DEPEND', ' '.join(pkg.require))
    print '-' * 80

    if pkg.info:
        for k, v in pkg.info.items():
            print '\n%s:' % k
            for i in v:
                print '\t%s %s %10s %s' % (i[0], i[1], i[2], i[3])

    print
    sys.exit(0)
