#!/usr/bin/env python2

from __future__ import print_function
import os, os.path, sys, errno, shutil, glob
import optparse
import subprocess as sp
import datetime as dt

import utils as U
import config_utils as C


# GENIE configuration

if not U.read_cgenie_config():
    sys.exit("GENIE not set up: run the setup.py script!")
scons = os.path.join(U.cgenie_root, 'scripts', 'scons', 'scons.py')
nccompare = os.path.join(U.cgenie_root, 'build', 'nccompare.exe')


#----------------------------------------------------------------------
#
#   LIST ALL EXISTING TESTS
#

def list():
    for d, ds, fs in os.walk(U.cgenie_test):
        if os.path.exists(os.path.join(d, 'test_info')):
            print(os.path.relpath(d, U.cgenie_test))


#----------------------------------------------------------------------
#
#   ADD A TEST
#

def add_test(test_job, test_name, restart):
    def yesno(prompt, default):
        opts = 'Yn' if default else 'yN'
        return raw_input(prompt + " [" + opts + "]: ") or default

    def has_job_output(jdir):
        for d, ds, fs in os.walk(os.path.join(jdir, 'output')):
            if fs != []: return True
        return False

    # Check for existence of required jobs, tests and directories.
    job_dir = os.path.join(U.cgenie_jobs, test_job)
    if not has_job_output(job_dir):
        sys.exit('Need to run job "' + test_job +
                 '" before adding it as a test')
    test_dir = os.path.join(U.cgenie_test, test_name)
    if not os.path.exists(job_dir):
        sys.exit('Job "' + test_job + '" does not exist')
    if os.path.exists(test_dir): sys.exit('Test already exists!')
    if restart:
        restart_test_dir = os.path.join(U.cgenie_test, restart)
        if not os.path.exists(restart_test_dir):
            sys.exit('Restart test "' + restart + '" does not exist')

    # Set up test directory and copy configuration files.
    os.makedirs(test_dir)
    shutil.copy(os.path.join(job_dir, 'config', 'config'),
                os.path.join(test_dir, 'test_info'))
    if restart:
        with open(os.path.join(test_dir, 'test_info'), 'a') as fp:
            print('restart_from: ' + restart, file=fp)
    for c in ['full_config', 'base_config', 'user_config']:
        if os.path.exists(os.path.join(job_dir, 'config', c)):
            shutil.copy(os.path.join(job_dir, 'config', c), test_dir)

    # Ask user which output NetCDF files to use for comparison and
    # copy them to the test "knowngood" directory.
    test_files = [ ]
    odir = os.path.join(job_dir, 'output')
    print('Select output files for test comparison:')
    for d, ds, fs in os.walk(odir):
        for f in fs:
            if f != '_restart.nc' and os.path.splitext(f)[1].lower() == '.nc':
                chkf = os.path.relpath(os.path.join(d, f), odir)
                if yesno('  ' + chkf, False):
                    src = os.path.join(job_dir, 'output', chkf)
                    dst = os.path.join(test_dir, 'knowngood', chkf)
                    if not os.path.exists(os.path.dirname(dst)):
                        os.makedirs(os.path.dirname(dst))
                    shutil.copyfile(src, dst)

    # Copy restart files if they exist and we aren't restarting from
    # another test.
    if not restart and os.path.exists(os.path.join(job_dir, 'restart')):
        shutil.copytree(os.path.join(job_dir, 'restart'),
                        os.path.join(test_dir, 'restart'))


#----------------------------------------------------------------------
#
#   RUN TESTS
#

# Make sure that the nccompare tool is available.

def ensure_nccompare():
    if os.path.exists(nccompare): return
    cmd = [scons, '-C', U.cgenie_root, os.path.join('build', 'nccompare.exe')]
    with open(os.devnull, 'w') as sink:
        status = sp.call(cmd, stdout=sink, stderr=sink)
    if status != 0:
        sys.exit('Couldn not build nccompare.exe program')


# Run a single test job and do results comparison: note that this uses
# *exactly* the same mechanisms that one would use to run these jobs
# by hand!

def do_run(t, rdir, logfp):
    os.chdir(U.cgenie_root)
    print('Running test "' + t + '"')
    print('Running test "' + t + '"', file=logfp)

    test_dir = os.path.join(U.cgenie_test, t)
    cmd = [os.path.join(os.curdir, 'new-job')]

    # Read test information file.
    config = { }
    with open(os.path.join(test_dir, 'test_info')) as fp:
        for line in fp:
            k, v = line.strip().split(':')
            config[k.strip()] = v.strip()
            have_full = os.path.exists(os.path.join(test_dir, 'full_config'))
            have_base = os.path.exists(os.path.join(test_dir, 'base_config'))
            have_user = os.path.exists(os.path.join(test_dir, 'user_config'))

    # Set up configuration file options for "new-job".
    if have_full:
        cmd.append('-c')
        cmd.append(os.path.join(test_dir, 'full_config'))
    elif have_base and have_user:
        cmd.append('-b')
        cmd.append(os.path.join(test_dir, 'base_config'))
        cmd.append('-u')
        cmd.append(os.path.join(test_dir, 'user_config'))
    else:
        sys.exit('Test "' + t + '" configured incorrectly!')

    # Set up other options for "new-job".
    cmd.append('-j')
    cmd.append(rdir)
    if 't100' in config and config['t100'] == 'True':
        cmd.append('--t100')
    cmd.append(t)
    cmd.append(config['run_length'])

    # Do job configuration, copying restart files if necessary.
    print('  Configuring job...')
    print('  Configuring job...', file=logfp)
    logfp.flush()
    if sp.check_call(cmd, stdout=logfp, stderr=logfp) != 0:
        sys.exit('Failed to configure test job')
    if 'restart_from' in config:
        rjob = config['restart_from']
        shutil.copytree(os.path.join(rdir, rjob, 'output'),
                        os.path.join(rdir, t, 'restart'))
    elif os.path.exists(os.path.join(test_dir, 'restart')):
        shutil.copytree(os.path.join(test_dir, 'restart'),
                        os.path.join(rdir, t, 'restart'))

    # Build and run job.
    os.chdir(os.path.join(rdir, t))
    print('  Building and running job...')
    print('  Building and running job...', file=logfp)
    logfp.flush()
    cmd = [os.path.join(os.curdir, 'go'), 'run', '--no-progress']
    if sp.check_call(cmd, stdout=logfp, stderr=logfp) != 0:
        sys.exit('Failed to build and run test job')

    # Compare results, walking over all known good files in the test
    # directory.
    print('  Checking results...')
    print('  Checking results...', file=logfp)
    logfp.flush()
    kg = os.path.join(test_dir, 'knowngood')
    passed = True
    for d, ds, fs in os.walk(kg):
        for f in fs:
            fullf = os.path.join(d, f)
            relname = os.path.relpath(fullf, kg)
            testf = os.path.join(rdir, t, 'output', relname)
            cmd = [nccompare, '-v', '-a', '6.0E-15', '-r', '35']
            cmd.append(fullf)
            cmd.append(testf)
            if sp.call(cmd, stdout=logfp, stderr=logfp):
                passed = False
                print('    FAILED: ' + relname)
                print('    FAILED: ' + relname, file=logfp)
            else:
                print('    OK: ' + relname)
                print('    OK: ' + relname, file=logfp)
    return passed


# Calculate transitive closure of restart dependency graph.

def restart_map(tests):
    res = { }
    check = set(tests)
    while len(check) != 0:
        for t in check:
            r = None
            ifile = os.path.join(U.cgenie_test, t, 'test_info')
            if not os.path.exists(ifile):
                sys.exit('Test "' + t + '" does not exist')
            with open(ifile) as fp:
                for line in fp:
                    if line.startswith('restart_from'):
                        r = line.split(':')[1].strip()
            res[t] = r
        check = set(res.values()) - set(res.keys()) - set([None])
    return res


# Topological sort of restart dependency graph.

def topological_sort(g):
    res = []
    while len(g) > 0:
        tails = filter(lambda k: not g[k], g.keys())
        res = res + tails
        for t in tails: g.pop(t)
        for k in g.keys():
            if g[k] in tails: g[k] = None
    return res


# Run a list of tests.

def run_tests(tests):
    ensure_nccompare()

    # Set up test jobs directory.
    label = dt.datetime.today().strftime('%Y%m%d-%H%M%S')
    rdir = os.path.join(U.cgenie_jobs, 'test-' + label)
    print('Test output in ' + rdir + '\n')
    os.makedirs(rdir)

    # Deal with "ALL" case.
    if tests == ['ALL']:
        tests = glob.glob(os.path.join(U.cgenie_test, '*'))
        tests = map(lambda p: os.path.relpath(p, U.cgenie_test),
                    filter(os.path.isdir, tests))

    # Determine leaf tests.
    ltests = []
    for tin in tests:
        for d, ds, fs in os.walk(os.path.join(U.cgenie_test, tin)):
            if os.path.exists(os.path.join(d, 'test_info')):
                ltests.append(os.path.relpath(d, U.cgenie_test))

    # Determine restart prerequisites for tests in list.
    restarts = restart_map(ltests)

    # Determine suitable execution order for tests from topological
    # sort of restart dependency graph.
    rtests = topological_sort(restarts)

    with open(os.path.join(rdir, 'test.log'), 'w') as logfp:
        summ = { t : do_run(t, rdir, logfp) for t in rtests }
    if len(summ.keys()) == 0:
        print('NO TESTS RUN')
    else:
        fmtlen = max(map(len, summ.keys())) + 3
        print('\nSUMMARY:\n')
        with open(os.path.join(rdir, 'summary.txt'), 'w') as sumfp:
            for t, r in summ.iteritems():
                print(t.ljust(fmtlen) + ('OK' if r else 'FAILED'))
                print(t.ljust(fmtlen) + ('OK' if r else 'FAILED'), file=sumfp)


# Command line arguments.

def usage():
    print("""
Usage: tests <command>

Commands:
  list                   List available tests
  run <test-name>...     Build test or group of tests
  add <job>              Add pre-existing job as test
  add <test-name>=<job>  Add pre-existing job as test with given name
        [-r <test>]      Restart from a pre-existing test
""")
    sys.exit()

if len(sys.argv) < 2: usage()
action = sys.argv[1]
if action == 'list':
    if len(sys.argv) != 2: usage()
    list()
elif action == 'add':
    if len(sys.argv) < 3: usage()
    job = sys.argv[2]
    if '=' in job:
        name, job = job.split('=')
    else:
        name = job
    restart = None
    if len(sys.argv) == 5 and sys.argv[3] == '-r':
        restart = sys.argv[4]
    elif len(sys.argv) != 3: usage()
    add_test(job, name, restart)
elif action == 'run':
    if len(sys.argv) < 3: usage()
    if 'ALL' in sys.argv[2:] and len(sys.argv) > 3:
        sys.exit('Must specify either "ALL" or a list of tests, not both')
    run_tests(sys.argv[2:])
else: usage()
