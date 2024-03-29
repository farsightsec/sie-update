#!/usr/bin/python3

# Copyright (c) 2009-2022 by Farsight Security, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
from subprocess import Popen, PIPE
import glob
import logging
import logging.handlers
import os
import random
import re
import sys
import tempfile
import time
import urllib.request, urllib.error, urllib.parse
import urllib.parse
import json

URL_BASE = 'http://update.sie-network.net:51080/sie-update/v2/'

SIE_UPDATE_VERSION = '0.5.0'

FNAME_CHALIAS = 'nmsgtool.chalias'
FNAME_GRALIAS = 'nmsg.gralias'
FNAME_OPALIAS = 'nmsg.opalias'

VERBOSE = False

class CommandFailed(Exception):
    pass

class UpdateFailed(Exception):
    pass

class CacheMiss(Exception):
    pass

def run_cmd(cmd, failok=False):
    if VERBOSE:
        print(cmd)
    p = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout = p.stdout.read().decode("utf-8")
    stderr = p.stderr.read().decode("utf-8")
    if VERBOSE:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
    rc = p.wait()
    if not failok and rc != 0:
        print('command "%s" returned non-zero exit code %d' % (cmd, rc), file=sys.stderr)
    if not failok and rc != 0:
        raise CommandFailed
    return (rc, stdout, stderr)

def get_cache_dir(base_dir, create=True):
    cache_dir = os.path.join(base_dir, 'sie-update')
    if os.path.exists(cache_dir) and not os.path.isdir(cache_dir):
        raise OSError(17, 
                "Cache exists and is not a directory '%s'" % cache_dir)

    if create and not os.path.exists(cache_dir):
        os.mkdir(cache_dir)

    return cache_dir

def cache_file_for_url(url, cache_dir):
    return os.path.join(cache_dir,
            os.path.basename(urllib.parse.urlparse(url).path))

def cache_fetch_contents(url, cache_dir, max_age=604800):
    cache_file = cache_file_for_url(url, cache_dir)

    if VERBOSE:
        print('fetching %s from cache file %s' % (url, cache_file), file=sys.stderr)

    if not os.path.isfile(cache_file):
        raise CacheMiss("Cache file '%s' does not exist")

    if max_age > 0 and time.time() - os.stat(cache_file).st_mtime > max_age:
        raise CacheMiss("Cache file '%s' has expired")

    with open(cache_file) as f:
        return f.read()

def cache_put_contents(url, data, cache_dir):
    cache_file = cache_file_for_url(url, cache_dir)
    if VERBOSE:
        print('storing %s to cache file %s' % (url, cache_file), file=sys.stderr)
    with tempfile.NamedTemporaryFile(dir=cache_dir, prefix='cache', delete=False) as f:
        f.write(data)
        f.file.close()
        os.chmod(f.name, 0o644)
        os.rename(f.name, cache_file)

def http_fetch_contents(url, cache_dir=None):
    if VERBOSE:
        print('Fetching %s...' % url)
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'sie-update/' + SIE_UPDATE_VERSION)
        data = urllib.request.urlopen(req).read()
        if cache_dir:
            cache_put_contents(url, data, cache_dir)
        return data
    except:
        print('Error: HTTP fetch failed for URL %s.' % url, file=sys.stderr)
        if cache_dir:
            try:
                print('Failing over to cache %s.' % cache_dir, file=sys.stderr)
                return cache_fetch_contents(url, cache_dir)
            except CacheMiss:
                print('Error: No cache for URL %s' % url, file=sys.stderr)
        raise UpdateFailed

def update_file(fname, url, cache_dir=None):
    old_contents = None
    if os.path.isfile(fname):
        old_contents = open(fname).read()
    new_contents = http_fetch_contents(url, cache_dir).decode("utf-8")
    if old_contents != new_contents:
        open(fname, 'w').write(new_contents)
        print('Updated %s from %s.' % (fname, url))

def do_update(funcs, iface, etcdir, preserve_vlans=[]):
    cache_dir = get_cache_dir(etcdir, create=True)
    hwaddr = funcs['get_hw_address'](iface)

    guest_base = urllib.parse.urljoin(URL_BASE, "guest/")
    guest_uri = urllib.parse.urljoin(guest_base, hwaddr.replace(':','-') + ".json")

    try:
        conf_json = http_fetch_contents(guest_uri, cache_dir)
    except:
        print('Error: no SIE configuration found for hardware address %s' % hwaddr, file=sys.stderr)
        raise UpdateFailed

    funcs['set_link_up'](iface)
    
    try:
        conf = json.loads(conf_json.decode("utf-8"))
    except:
        print('Error: failed to parse SIE configuration\n', file=sys.stderr)
        raise

    vlans = set([c['vlan'] for c in conf['ifconfig']])
    cur_vlans = funcs['get_vlans'](iface)
    for vlan in cur_vlans.difference(vlans).difference(preserve_vlans):
        funcs['remove_vlan'](iface, vlan)
    
    for c in conf['ifconfig']:
        if c['vlan'] in preserve_vlans:
            continue
        funcs['set_vlan_up'](iface, c['vlan'], c['ip'])

    url_chalias = urllib.parse.urljoin(guest_base, conf['files']['chalias'])
    url_gralias = urllib.parse.urljoin(guest_base, conf['files']['gralias'])
    url_opalias = urllib.parse.urljoin(guest_base, conf['files']['opalias'])

    update_file(os.path.join(etcdir, FNAME_CHALIAS), url_chalias, cache_dir)
    update_file(os.path.join(etcdir, FNAME_GRALIAS), url_gralias, cache_dir)
    update_file(os.path.join(etcdir, FNAME_OPALIAS), url_opalias, cache_dir)

def _linux_get_hw_address(iface):
    try:
        hwaddr = open('/sys/class/net/%s/address' % iface).read().rstrip()
        return hwaddr
    except:
        print('Error: unable to determine hardware address for interface %s' % iface, file=sys.stderr)
        raise UpdateFailed

def _freebsd_get_hw_address(iface):
    try:
        rc, stdout, stderr = run_cmd('ifconfig %s' % iface)
        hwaddr = re.findall('ether ([0-9a-f:]+)', stdout)[0]
        return hwaddr
    except:
        print('Error: unable to determine hardware address for interface %s' % iface, file=sys.stderr)
        raise UpdateFailed

def _linux_get_vlans(iface):
    vlans = set()
    for x in glob.glob('/proc/net/vlan/%s.*' % iface):
        vlan = os.path.basename(x).split('%s.' % iface, 1)[1]
        vlans.add(int(vlan))
    return vlans

def _freebsd_get_vlans(iface):
    vlans = set()
    try:
        rc, stdout, stderr = run_cmd('ifconfig | grep "^vlan"', failok=True)
        if rc == 0:
            for line in stdout.strip().split('\n'):
                s = line.split(':', 1)[0].split('vlan', 1)[1]
                vlans.add(int(s))
    except:
        print('Error: unable to enumerate VLAN IDs for interface %s' % iface, file=sys.stderr)
        raise UpdateFailed
    return vlans

def _linux_ip_addr_add(ip, iface, netmask=24):
    run_cmd('ip addr add %s/%s dev %s' % (ip, netmask, iface))

def _freebsd_ip_addr_add(ip, iface, netmask=24):
    netmask = hex((1 << 32) - (1 << (32 - netmask))) # bah
    run_cmd('ifconfig %s alias %s netmask %s' % (iface, ip, netmask))

def _linux_set_link_up(iface):
    rc, stdout, stderr = run_cmd('ip link show %s' % iface, failok=True)
    if rc != 0:
        print('Error: unable to bring up SIE network interface %s' % iface, file=sys.stderr)
        raise UpdateFailed
    if len(stdout) > 0 and not ('mtu 9000' in stdout and 'state UP' in stdout):
        run_cmd('ip link set up %s mtu 9000' % iface)

def _freebsd_set_link_up(iface):
    rc, stdout, stderr = run_cmd('ifconfig %s' % iface, failok=True)
    if rc != 0:
        print('Error: unable to bring up SIE network interface %s' % iface, file=sys.stderr)
        raise UpdateFailed

    if len(stdout) > 0 and not ('mtu 9000' in stdout and 'UP' in stdout):
        run_cmd('ifconfig %s mtu 9000 up' % iface)

def _linux_set_vlan_mtu(iface, vlan, mtu):
    run_cmd('ip link set mtu %s dev %s.%s' % (mtu, iface, vlan))

def _freebsd_set_vlan_mtu(iface, vlan, mtu):
    run_cmd('ifconfig vlan%s mtu %s' % (vlan, mtu))

def _linux_set_vlan_up(iface, vlan, ip, netmask=24):
    vlan_iface = '%s.%s' % (iface, vlan)

    rc, stdout, stderr = run_cmd('ip addr show %s' % vlan_iface, failok=True)
    if rc != 0:
        run_cmd('ip link add link %s name %s type vlan id %s' % (iface, vlan_iface, vlan))
        run_cmd('sysctl -q -w net.ipv6.conf.%s/%s.disable_ipv6=1' % (iface, vlan))
        _linux_ip_addr_add(ip, vlan_iface)
        print('Added new VLAN %s to %s.' % (vlan, iface))
    else:
        current_ips = set(re.findall('inet ([0-9./]+)', stdout))
        ipnm = '%s/%s' % (ip, netmask)
        if ipnm in current_ips:
            rm_ips = set(current_ips)
            rm_ips.remove(ipnm)
            if rm_ips:
                for x in rm_ips:
                    print('Removing obsolete IP address %s from interface %s' % (x, vlan_iface))
                    run_cmd('ip addr del %s dev %s' % (x, vlan_iface))
        else:
            run_cmd('ip addr flush dev %s' % vlan_iface)
            _linux_ip_addr_add(ip, vlan_iface, netmask)
    run_cmd('ip link set up dev %s' % vlan_iface)

def _freebsd_set_vlan_up(iface, vlan, ip, netmask=24):
    vlan_iface = 'vlan%s' % vlan

    rc, stdout, stderr = run_cmd('ifconfig %s' % vlan_iface, failok=True)
    if rc != 0:
        run_cmd('ifconfig %s create vlan %s vlandev %s' % (vlan_iface, vlan, iface))
        _freebsd_ip_addr_add(ip, vlan_iface)
        print('Added new VLAN %s to %s.' % (vlan, iface))
    else:
        current_ips = set(re.findall('inet ([0-9.]+)', stdout))
        rm_ips = set(current_ips)
        if ip in current_ips:
            rm_ips.remove(ip)
        else:
            _freebsd_ip_addr_add(ip, vlan_iface, netmask)
        if rm_ips:
            for x in rm_ips:
                run_cmd('ifconfig %s -alias %s' % (vlan_iface, x))

def _linux_remove_vlan(iface, vlan):
    run_cmd('ip link del dev %s.%s' % (iface, vlan))
    print('Removed old VLAN %s from %s.' % (vlan, iface))

def _freebsd_remove_vlan(iface, vlan):
    run_cmd('ifconfig vlan%s destroy' % vlan)
    print('Removed old VLAN %s from %s.' % (vlan, iface))

def main():
    global URL_BASE
    global VERBOSE

    linux_net_funcs = {
        'get_hw_address':   _linux_get_hw_address,
        'get_vlans':        _linux_get_vlans,
        'ip_addr_add':      _linux_ip_addr_add,
        'set_link_up':      _linux_set_link_up,
        'set_vlan_up':      _linux_set_vlan_up,
        'set_vlan_mtu':     _linux_set_vlan_mtu,
        'remove_vlan':      _linux_remove_vlan
    }

    freebsd_net_funcs = {
        'get_hw_address':   _freebsd_get_hw_address,
        'get_vlans':        _freebsd_get_vlans,
        'ip_addr_add':      _freebsd_ip_addr_add,
        'set_link_up':      _freebsd_set_link_up,
        'set_vlan_up':      _freebsd_set_vlan_up,
        'set_vlan_mtu':     _freebsd_set_vlan_mtu,
        'remove_vlan':      _freebsd_remove_vlan
    }

    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--interface', dest='interface',
            action='append', help='SIE network interface')
    parser.add_argument('-e', '--etcdir', dest='etcdir', default='/etc',
            help='system configuration directory')
    parser.add_argument('-v', '--verbose', dest='verbose', default=VERBOSE,
            action='store_true', help='verbose mode')
    parser.add_argument('-d', '--daemon', dest='daemon', action='store_true',
            help='run as daemon')
    parser.add_argument('-t', '--poll-time', dest='poll_time', default=3600,
            type=float, help='poll time for daemon')
    parser.add_argument('-l', '--log-file', dest='log_file',
            default='/var/log/sie-update.log',
            help='log file for daemon mode')
    parser.add_argument('-p', '--pid-file', dest='pid_file',
            default='/var/run/sie-update.pid',
            help='pid file for daemon mode')
    parser.add_argument('-P', '--preserve', dest='preserve',
            metavar='[int or int-int]',
            nargs='*', help='Preserve vlans')
    
    args = parser.parse_args()

    VERBOSE = args.verbose

    if not os.path.isdir(args.etcdir):
        parser.error('path does not exist: %s' % args.etcdir)

    if not args.interface:
        parser.error('SIE network interface (-i) required')

    kernel = os.uname()[0]
    if kernel == 'Linux':
        net_funcs = linux_net_funcs
    elif kernel == 'FreeBSD':
        net_funcs = freebsd_net_funcs
    else:
        print('Error: unsupported system: %s' % kernel, file=sys.stderr)
        sys.exit(1)

    preserve_vlans = set()
    if args.preserve:
        for vlan_spec in args.preserve:
            try:
                preserve_vlans.add(int(vlan_spec))
            except ValueError:
                low_str,_,high_str = vlan_spec.partition('-')
                try:
                    preserve_vlans.update(list(range(int(low_str), int(high_str)+1)))
                except ValueError:
                    parser.error('Invalid vlan_spec: {!r}'.format(vlan_spec))

    if not args.daemon:
        try:
            for iface in args.interface:
                do_update(net_funcs, iface, args.etcdir, preserve_vlans=preserve_vlans)
        except UpdateFailed as e:
            sys.exit(1)
    else:
        try:
            import daemon
        except ImportError:
            print("Daemon mode requires the 'daemon' python module from:", file=sys.stderr)
            print("https://pypi.python.org/pypi/python-daemon", file=sys.stderr)
            sys.exit(1)

        try:
            from lockfile.pidlockfile import PIDLockFile
        except ImportError:
            # lockfile is missing or a version predating the move
            # of PIDLockFile from daemon to lockfile. If the latter,
            # attempt to load PIDLockFile from daemon.
            try:
                from daemon.pidlockfile import PIDLockFile
            except ImportError:
                print("Daemon mode requires the 'lockfile' python module from:", file=sys.stderr)
                print("https://pypi.python.org/pypi/lockfile", file=sys.stderr)

        args.pid_file = os.path.abspath(args.pid_file)
        args.log_file = os.path.abspath(args.log_file)
        args.etcdir = os.path.abspath(args.etcdir)

        with daemon.DaemonContext(pidfile=PIDLockFile(args.pid_file)):
            class file_wrapper:
                def __init__(self, severity=logging.INFO):
                    self._severity = severity
                def flush(self):
                    pass
                def write(self, msg):
                    logger = logging.getLogger('sie-update')
                    msg = msg.rstrip()
                    if msg:
                        logger.log(self._severity, msg)

            # daemon.DaemonContext has devnulled stdout and stderr
            sys.stdout=file_wrapper()
            sys.stderr=file_wrapper(logging.ERROR)

            handler = logging.handlers.RotatingFileHandler(
                    filename=args.log_file, maxBytes=10485760, backupCount=1)
            formatter = logging.Formatter(
                    '%(asctime)s %(levelname)s: %(message)s')
            handler.setFormatter(formatter)

            logger = logging.getLogger('sie-update')
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)

            logger.info('Starting daemon thread')

            while True:
                try:
                    for iface in args.interface:
                        do_update(net_funcs, iface, args.etcdir, preserve_vlans=preserve_vlans)
                except UpdateFailed as e:
                    pass
                except:
                    print("Unhandled exception:", file=sys.stderr)
                    sys.excepthook(*sys.exc_info())
                time.sleep(random.gauss(args.poll_time, args.poll_time/10))

if __name__ == '__main__':
    main()
