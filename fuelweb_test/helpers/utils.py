#    Copyright 2014 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import division

import copy
# pylint: disable=no-name-in-module
from distutils import version
# pylint: enable=no-name-in-module
import inspect
import json
import os
import posixpath
import re
import signal
import time
import traceback

import netaddr
from proboscis import asserts
from proboscis.asserts import assert_true
from proboscis.asserts import assert_equal
# pylint: disable=import-error
from six.moves import configparser
# pylint: enable=import-error
# pylint: disable=redefined-builtin
from six.moves import xrange
# pylint: enable=redefined-builtin
import yaml

from fuelweb_test import logger
from fuelweb_test import logwrap
from fuelweb_test import settings
from fuelweb_test.helpers.ssh_manager import SSHManager
from gates_tests.helpers import exceptions


@logwrap
def get_yaml_to_json(node_ssh, filename):
    cmd = ("python -c 'import sys, yaml, json; json.dump("
           "yaml.load(sys.stdin),"
           " sys.stdout)' < {0}").format(filename)
    err_res = ''
    res = node_ssh.execute(cmd)
    err_res.join(res['stderr'])
    asserts.assert_equal(
        res['exit_code'], 0,
        'Command {0} execution failed '
        'with message {1}'.format(cmd, err_res))
    return res['stdout']


@logwrap
def put_json_on_remote_from_dict(remote, src_dict, cluster_id):
    cmd = ('python -c "import json; '
           'data=json.dumps({0}); print data"').format(src_dict)
    result = remote.execute(
        '{0} > /var/log/network_{1}.json'.format(cmd, cluster_id))
    asserts.assert_equal(
        result['exit_code'], 0,
        'Failed to run cmd {0} with result {1}'.format(cmd, result))


@logwrap
def nova_service_get_pid(node_ssh, nova_services=None):
    pid_dict = {}
    for el in nova_services:
        cmd = "pgrep {0}".format(el)
        pid_dict[el] = node_ssh.execute(cmd)['stdout']
        logger.debug('current dict is {0}'. format(pid_dict))
    return pid_dict


@logwrap
def check_if_service_restarted(node_ssh, services_list=None,
                               pattern='(re)?start', skip=0):
    if services_list:
        # from the log file {2}, scan all lines after line {0} with the
        # pattern {1} to find restarted services, print their names to stdout
        cmd = ("awk 'NR >= {0} && /{1}/ {{print $11}}' {2}"
               .format(skip, pattern, '/var/log/puppet.log'))
        res = ''.join(node_ssh.execute(cmd)['stdout'])
        logger.debug('Next services were restarted {0}'.format(res))
        for service in services_list:
            asserts.assert_true(
                any(service in x for x in res),
                'Seems service {0} was not restarted {1}'.format(service, res))


@logwrap
def pull_out_logs_via_ssh(admin_remote, name,
                          logs_dirs=('/var/log/', '/root/', '/etc/fuel/')):
    def _compress_logs(_dirs, _archive_path):
        cmd = 'tar --absolute-names --warning=no-file-changed -czf {t} {d}'.\
            format(t=_archive_path, d=' '.join(_dirs))
        result = admin_remote.execute(cmd)
        if result['exit_code'] != 0:
            logger.error("Compressing of logs on master node failed: {0}".
                         format(result))
            return False
        return True

    archive_path = '/var/tmp/fail_{0}_diagnostic-logs_{1}.tgz'.format(
        name, time.strftime("%Y_%m_%d__%H_%M_%S", time.gmtime()))

    try:
        if _compress_logs(logs_dirs, archive_path):
            if not admin_remote.download(archive_path, settings.LOGS_DIR):
                logger.error(("Downloading of archive with logs failed, file"
                              "wasn't saved on local host"))
    except Exception:
        logger.error(traceback.format_exc())


@logwrap
def store_astute_yaml(env):
    func_name = get_test_method_name()
    nailgun_nodes = env.fuel_web.client.list_nodes()

    def store_astute_yaml_for_one_node(nailgun_node):
        ssh_manager = SSHManager()
        if 'roles' not in nailgun_node:
            return None
        errmsg = 'Downloading "{0}.yaml" from the {1} failed'
        msg = 'File "{0}.yaml" was downloaded from the {1}'
        nodename = nailgun_node['name']
        ip = nailgun_node['ip']
        for role in nailgun_node['roles']:
            filename = '{0}/{1}-{2}-{3}.yaml'.format(settings.LOGS_DIR,
                                                     func_name,
                                                     nodename,
                                                     role)

            if not ssh_manager.isfile_on_remote(ip,
                                                '/etc/{0}.yaml'.format(role)):
                role = 'primary-' + role
            if ssh_manager.download_from_remote(ip,
                                                '/etc/{0}.yaml'.format(role),
                                                filename):
                logger.info(msg.format(role, nodename))
            else:
                logger.error(errmsg.format(role, nodename))
        if settings.DOWNLOAD_FACTS:
            fact_filename = re.sub(r'-\w*\.', '-facts.', filename)
            generate_facts(ip)
            if ssh_manager.download_from_remote(ip,
                                                '/tmp/facts.yaml',
                                                fact_filename):
                logger.info(msg.format('facts', nodename))
            else:
                logger.error(errmsg.format('facts', nodename))

    try:
        for node in nailgun_nodes:
            store_astute_yaml_for_one_node(node)
    except Exception:
        logger.error(traceback.format_exc())


@logwrap
def generate_facts(ip):
    ssh_manager = SSHManager()
    facter_dir = '/var/lib/puppet/lib/facter'
    exluded_facts = ['naily.rb']

    if not ssh_manager.isdir_on_remote(ip, facter_dir):
        ssh_manager.mkdir_on_remote(ip, facter_dir)
        logger.debug('Directory {0} was created'.format(facter_dir))

    ssh_manager.execute_on_remote(ip, 'rm -f {0}/*.rb'.format(facter_dir))
    logger.debug('rb files were removed from {0}'.format(facter_dir))

    facts_files = ssh_manager.execute_on_remote(
        ip,
        'find /etc/puppet/modules/ -wholename "*/lib/facter/*.rb"')['stdout']
    facts_files = [i.strip() for i in facts_files]
    logger.debug('The following facts {0} will'
                 ' be copied to {1}'.format(facts_files, facter_dir))
    for fact in facts_files:
        if not fact or re.sub(r'.*/', '', fact) in exluded_facts:
            continue
        ssh_manager.execute_on_remote(ip,
                                      'cp {0} {1}/'.format(fact, facter_dir))
    logger.debug('Facts were copied')

    ssh_manager.execute_on_remote(ip, 'facter -p -y > /tmp/facts.yaml')
    logger.info('Facts yaml was created')

    ssh_manager.execute_on_remote(ip, 'rm -f {0}/*.rb'.format(facter_dir))
    logger.debug('rb files were removed from {0}'.format(facter_dir))


@logwrap
def get_node_packages(remote, func_name, node_role,
                      packages_dict, release=settings.OPENSTACK_RELEASE):
    if settings.OPENSTACK_RELEASE_UBUNTU in release:
        cmd = "dpkg-query -W -f='${Package} ${Version}'\r"
    else:
        cmd = 'rpm -qa --qf "%{name} %{version}"\r'
    node_packages = remote.execute(cmd)['stdout'][0].split('\r')[:-1]

    logger.debug("node packages are {0}".format(node_packages))
    packages_dict[func_name][node_role] = node_packages\
        if node_role not in packages_dict[func_name].keys()\
        else list(set(packages_dict[func_name][node_role]) |
                  set(node_packages))
    return packages_dict


@logwrap
def store_packages_json(env):
    func_name = "".join(get_test_method_name())
    packages = {func_name: {}}
    cluster_id = env.fuel_web.get_last_created_cluster()
    for nailgun_node in env.fuel_web.client.list_cluster_nodes(cluster_id):
        role = '_'.join(nailgun_node['roles'])
        logger.debug('role is {0}'.format(role))
        with env.d_env.get_ssh_to_remote(nailgun_node['ip']) as remote:
            packages = get_node_packages(remote, func_name, role, packages)
    packages_file = '{0}/packages.json'.format(settings.LOGS_DIR)
    if os.path.isfile(packages_file):
        with open(packages_file, 'r') as outfile:
            try:
                file_packages = json.load(outfile)
            except:
                file_packages = {}
        packages.update(file_packages)
    with open(packages_file, 'w') as outfile:
        json.dump(packages, outfile)


@logwrap
def get_test_method_name():
    # Find the name of the current test in the stack. It can be found
    # right under the class name 'NoneType' (when proboscis
    # run the test method with unittest.FunctionTestCase)
    stack = inspect.stack()
    method = ''
    for m in stack:
        if 'self' in m[0].f_locals:
            if m[0].f_locals['self'].__class__.__name__ == 'NoneType':
                break
            method = m[3]
    return method


def get_current_env(args):
    if args[0].__class__.__name__ == "EnvironmentModel":
        return args[0]
    elif args[0].__class__.__name__ == "FuelWebClient":
        return args[0].environment
    else:
        try:
            return args[0].env
        except AttributeError as attr_err:
            logger.error("Class '{0}' doesn't have 'env' attribute! {1}"
                         .format(args[0].__class__.__name__, attr_err.message))
            raise


@logwrap
def update_yaml(yaml_tree=None, yaml_value='', is_uniq=True,
                yaml_file=settings.TIMESTAT_PATH_YAML):
    """Store/update a variable in YAML file.

    yaml_tree - path to the variable in YAML file, will be created if absent,
    yaml_value - value of the variable, will be overwritten if exists,
    is_uniq - If false, add the unique two-digit suffix to the variable name.
    """
    if yaml_tree is None:
        yaml_tree = []
    yaml_data = {}
    if os.path.isfile(yaml_file):
        with open(yaml_file, 'r') as f:
            yaml_data = yaml.load(f)

    # Walk through the 'yaml_data' dict, find or create a tree using
    # sub-keys in order provided in 'yaml_tree' list
    item = yaml_data
    for n in yaml_tree[:-1]:
        if n not in item:
            item[n] = {}
        item = item[n]

    if is_uniq:
        last = yaml_tree[-1]
    else:
        # Create an uniq suffix in range '_00' to '_99'
        for n in range(100):
            last = str(yaml_tree[-1]) + '_' + str(n).zfill(2)
            if last not in item:
                break

    item[last] = yaml_value
    with open(yaml_file, 'w') as f:
        yaml.dump(yaml_data, f, default_flow_style=False)


class TimeStat(object):
    """ Context manager for measuring the execution time of the code.
    Usage:
    with TimeStat([name],[is_uniq=True]):
    """

    def __init__(self, name=None, is_uniq=False):
        if name:
            self.name = name
        else:
            self.name = 'timestat'
        self.is_uniq = is_uniq
        self.begin_time = 0
        self.end_time = 0
        self.total_time = 0

    def __enter__(self):
        self.begin_time = time.time()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.end_time = time.time()
        self.total_time = self.end_time - self.begin_time

        # Create a path where the 'self.total_time' will be stored.
        yaml_path = []

        # There will be a list of one or two yaml subkeys:
        # - first key name is the method name of the test
        method_name = get_test_method_name()
        if method_name:
            yaml_path.append(method_name)

        # - second (subkey) name is provided from the decorator (the name of
        # the just executed function), or manually.
        yaml_path.append(self.name)

        try:
            update_yaml(yaml_path, '{:.2f}'.format(self.total_time),
                        self.is_uniq)
        except Exception:
            logger.error("Error storing time statistic for {0}"
                         " {1}".format(yaml_path, traceback.format_exc()))
            raise

    @property
    def spent_time(self):
        return time.time() - self.begin_time


def install_pkg(remote, pkg_name):
    """Install a package <pkg_name> on node
    :param remote: SSHClient to remote node
    :param pkg_name: name of a package
    :return: exit code of installation
    """
    remote_status = remote.execute("rpm -q '{0}'".format(pkg_name))
    if remote_status['exit_code'] == 0:
        logger.info("Package '{0}' already installed.".format(pkg_name))
    else:
        logger.info("Installing package '{0}' ...".format(pkg_name))
        remote_status = remote.execute("yum -y install {0}"
                                       .format(pkg_name))
        logger.info("Installation of the package '{0}' has been"
                    " completed with exit code {1}"
                    .format(pkg_name, remote_status['exit_code']))
    return remote_status['exit_code']


def install_pkg_2(ip, pkg_name, port=22):
    """Install a package <pkg_name> on node
    :param ip: ip of node
    :param pkg_name: name of a package
    :param port: ssh port
    :return: exit code of installation
    """
    ssh_manager = SSHManager()
    remote_status = ssh_manager.execute(
        ip=ip,
        port=port,
        cmd="rpm -q '{0}'".format(pkg_name)
    )
    if remote_status['exit_code'] == 0:
        logger.info("Package '{0}' already installed.".format(pkg_name))
    else:
        logger.info("Installing package '{0}' ...".format(pkg_name))
        remote_status = ssh_manager.execute(
            ip=ip,
            port=port,
            cmd="yum -y install {0}".format(pkg_name)
        )
        logger.info("Installation of the package '{0}' has been"
                    " completed with exit code {1}"
                    .format(pkg_name, remote_status['exit_code']))
    return remote_status['exit_code']


def cond_upload(remote, source, target, condition=''):
    # Upload files only if condition in regexp matches filenames
    if remote.isdir(target):
        target = posixpath.join(target, os.path.basename(source))

    source = os.path.expanduser(source)
    if not os.path.isdir(source):
        if re.match(condition, source):
            remote.upload(source, target)
            logger.debug("File '{0}' uploaded to the remote folder '{1}'"
                         .format(source, target))
            return 1
        else:
            logger.debug("Pattern '{0}' doesn't match the file '{1}', "
                         "uploading skipped".format(condition, source))
            return 0

    files_count = 0
    for rootdir, _, files in os.walk(source):
        targetdir = os.path.normpath(
            os.path.join(
                target,
                os.path.relpath(rootdir, source))).replace("\\", "/")

        remote.mkdir(targetdir)

        for entry in files:
            local_path = os.path.join(rootdir, entry)
            remote_path = posixpath.join(targetdir, entry)
            if re.match(condition, local_path):
                remote.upload(local_path, remote_path)
                files_count += 1
                logger.debug("File '{0}' uploaded to the remote folder '{1}'"
                             .format(source, target))
                if 'deb' in entry:
                    continue
                entry_name = entry[0:entry.rfind('-', 0, entry.rfind('-'))]
                asserts.assert_true(compare_packages_version(
                    remote, entry_name, remote_path))
            else:
                logger.debug("Pattern '{0}' doesn't match the file '{1}', "
                             "uploading skipped".format(condition, local_path))
    return files_count


def run_on_remote(*args, **kwargs):
    if 'jsonify' in kwargs:
        if kwargs['jsonify']:
            return run_on_remote_get_results(*args, **kwargs)['stdout_json']
    else:
        return run_on_remote_get_results(*args, **kwargs)['stdout']


@logwrap
def run_on_remote_get_results(remote, cmd, clear=False, err_msg=None,
                              jsonify=False, assert_ec_equal=None,
                              raise_on_assert=True):
    # TODO(ivankliuk): move it to devops.helpers.SSHClient
    """Execute ``cmd`` on ``remote`` and return result.

    :param remote: devops.helpers.helpers.SSHClient
    :param cmd: command to execute on remote host
    :param clear: clear SSH session
    :param err_msg: custom error message
    :param assert_ec_equal: list of expected exit_code
    :param raise_on_assert: Boolean
    :return: dict
    :raise: Exception
    """
    if assert_ec_equal is None:
        assert_ec_equal = [0]
    result = remote.execute(cmd)
    if result['exit_code'] not in assert_ec_equal:
        error_details = {
            'command': cmd,
            'host': remote.host,
            'stdout': result['stdout'],
            'stderr': result['stderr'],
            'exit_code': result['exit_code']}

        error_msg = (err_msg or "Unexpected exit_code returned:"
                                " actual {0}, expected {1}."
                     .format(error_details['exit_code'],
                             ' '.join(map(str, assert_ec_equal))))
        log_msg = ("{0}  Command: '{1}'  Details: {2}".format(error_msg,
                                                              cmd,
                                                              error_details))
        logger.error(log_msg)
        if raise_on_assert:
            raise Exception(log_msg)

    if clear:
        remote.clear()

    result['stdout_str'] = ''.join(result['stdout'])
    result['stdout_len'] = len(result['stdout'])
    result['stderr_str'] = ''.join(result['stderr'])
    result['stderr_len'] = len(result['stderr'])

    if jsonify:
        try:
            result['stdout_json'] = json_deserialize(result['stdout_str'])
        except Exception:
            error_msg = (
                "Unable to deserialize output of command"
                " '{0}' on host {1}".format(cmd, remote.host))
            logger.error(error_msg)
            raise Exception(error_msg)

    return result


def json_deserialize(json_string):
    """
    Deserialize json_string and return object

    :param json_string: string or list with json
    :return: obj
    :raise: Exception
    """
    if isinstance(json_string, list):
        json_string = ''.join(json_string)

    try:
        obj = json.loads(json_string)
    except Exception:
        log_msg = "Unable to deserialize"
        logger.error("{0}. Actual string:\n{1}".format(log_msg, json_string))
        raise Exception(log_msg)
    return obj


def check_distribution():
    """Checks whether distribution is supported.

    :return: None
    :raise: Exception
    """
    if settings.OPENSTACK_RELEASE not in (settings.OPENSTACK_RELEASE_CENTOS,
                                          settings.OPENSTACK_RELEASE_UBUNTU):
        error_msg = ("{0} distribution is not supported!".format(
            settings.OPENSTACK_RELEASE))
        logger.error(error_msg)
        raise Exception(error_msg)


@logwrap
def get_network_template(template_name):
    templates_path = ('{0}/fuelweb_test/network_templates/'.format(
        os.environ.get("WORKSPACE", "./")))
    template = os.path.join(templates_path, '{}.yaml'.format(template_name))
    if os.path.exists(template):
        with open(template) as template_file:
            return yaml.load(template_file)


@logwrap
def get_net_settings(remote, skip_interfaces=None):
    if skip_interfaces is None:
        skip_interfaces = set()
    net_settings = dict()
    interface_cmd = ('awk \'$1~/:/{split($1,iface,":"); print iface[1]}\''
                     ' /proc/net/dev')
    vlan_cmd = 'awk \'$1~/\./{print $1}\' /proc/net/vlan/config'
    bond_cmd = ('awk \'{gsub(" ","\\n"); print}\' '
                '/sys/class/net/bonding_masters')
    bridge_cmd = 'ls -d1 /sys/class/net/*/bridge/ | cut -d/ -f5'
    ip_cmd = 'ip -o -4 addr show dev {0} | awk \'{{print $4}}\''
    bond_mode_cmd = 'awk \'{{print $1}}\' /sys/class/net/{0}/bonding/mode'
    bond_slaves_cmd = ('awk \'{{gsub(" ","\\n"); print}}\' '
                       '/sys/class/net/{0}/bonding/slaves')
    bridge_slaves_cmd = 'ls -1 /sys/class/net/{0}/brif/'

    node_interfaces = [l.strip() for l in run_on_remote(remote, interface_cmd)
                       if not any(re.search(regex, l.strip()) for regex
                                  in skip_interfaces)]
    node_vlans = [l.strip() for l in run_on_remote(remote, vlan_cmd)]
    node_bonds = [l.strip() for l in run_on_remote(remote, bond_cmd)]
    node_bridges = [l.strip() for l in run_on_remote(remote, bridge_cmd)]

    for interface in node_interfaces:
        bond_mode = None
        bond_slaves = None
        bridge_slaves = None
        if interface in node_vlans:
            if_type = 'vlan'
        elif interface in node_bonds:
            if_type = 'bond'
            bond_mode = ''.join(
                [l.strip() for l in
                 run_on_remote(remote, bond_mode_cmd.format(interface))])
            bond_slaves = set(
                [l.strip() for l in
                 run_on_remote(remote, bond_slaves_cmd.format(interface))]
            )
        elif interface in node_bridges:
            if_type = 'bridge'
            bridge_slaves = set(
                [l.strip() for l in
                 run_on_remote(remote, bridge_slaves_cmd.format(interface))
                 if not any(re.search(regex, l.strip())
                            for regex in skip_interfaces)]
            )
        else:
            if_type = 'common'
        if_ips = set(
            [l.strip()
             for l in run_on_remote(remote, ip_cmd.format(interface))]
        )

        net_settings[interface] = {
            'type': if_type,
            'ip_addresses': if_ips,
            'bond_mode': bond_mode,
            'bond_slaves': bond_slaves,
            'bridge_slaves': bridge_slaves
        }
    return net_settings


@logwrap
def get_ip_listen_stats(remote, proto='tcp'):
    # If bindv6only is disabled, then IPv6 sockets listen on IPv4 too
    check_v6_bind_cmd = 'cat /proc/sys/net/ipv6/bindv6only'
    bindv6only = ''.join([l.strip()
                          for l in run_on_remote(remote, check_v6_bind_cmd)])
    check_v6 = bindv6only == '0'
    if check_v6:
        cmd = ("awk '$4 == \"0A\" {{gsub(\"00000000000000000000000000000000\","
               "\"00000000\", $2); print $2}}' "
               "/proc/net/{0} /proc/net/{0}6").format(proto)
    else:
        cmd = "awk '$4 == \"0A\" {{print $2}}' /proc/net/{0}".format(proto)
    return [l.strip() for l in run_on_remote(remote, cmd)]


@logwrap
def node_freemem(remote, unit='MB'):
    """Return free memory and swap

    units :type : str, can be a KB, MB, GB. Default is MB
    """
    denominators = {
        'KB': 1,
        'MB': 1024,
        'GB': 1024 ** 2
    }
    denominator = denominators.get(unit, denominators['MB'])
    cmd_mem_free = 'free -k | grep Mem:'
    cmd_swap_free = 'free -k | grep Swap:'
    mem_free = run_on_remote(remote, cmd_mem_free)[0]
    swap_free = run_on_remote(remote, cmd_swap_free)[0]
    ret = {
        "mem": {
            "total": int(mem_free.split()[1]) // denominator,
            "used": int(mem_free.split()[2]) // denominator,
            "free": int(mem_free.split()[3]) // denominator,
            "shared": int(mem_free.split()[4]) // denominator,
            "buffers": int(mem_free.split()[5]) // denominator,
            "cached": int(mem_free.split()[6]) // denominator
        },
        "swap": {
            "total": int(swap_free.split()[1]) // denominator,
            "used": int(swap_free.split()[2]) // denominator,
            "free": int(swap_free.split()[3]) // denominator,
        }
    }
    return ret


def hiera_json_out(node_ip, parameter):
    hiera_cmd = "ruby -rhiera -rjson -e \"h = Hiera.new(); " \
                "Hiera.logger = 'noop'; " \
                "puts JSON.dump(h.lookup(\'{0}\', " \
                "[], {{}}, nil, nil))\"".format(parameter)
    ssh_manager = SSHManager()
    config = ssh_manager.execute_on_remote(
        ip=node_ip,
        cmd=hiera_cmd,
        jsonify=True,
        err_msg='Cannot get floating ranges')['stdout_json']
    return config


def generate_floating_ranges(start_ip, end_ip, step):
    """Generating floating range by first and last ip with any step

    :param start_ip: first ip address in floating range
    :param end_ip: last ip address in floating range
    :param step: count of ip addresses in floating range
    :return:
    """
    ranges = []
    ip_start = netaddr.IPAddress(str(start_ip))
    ip_end = netaddr.IPAddress(str(end_ip))
    while ip_end - step > ip_start:
        ranges.append([str(ip_start), str(ip_start + step)])
        ip_start += (step + 1)
    return ranges


def get_node_hiera_roles(remote):
    """Get hiera roles assigned to host

    :param :remote: SSHClient to node
        :rtype: dict host plus role
    """
    cmd = 'hiera roles'
    roles = ''.join(run_on_remote(remote, cmd)).strip()
    # Content string with roles like a ["ceph-osd", "controller"] to list
    return [role.strip('" ') for role in roles.strip("[]").split(',')]


class RunLimit(object):
    def __init__(self, seconds=60, error_message='Timeout'):
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum, frame):
        raise TimeoutException(self.error_message)

    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, exc_type, value, traceback):
        signal.alarm(0)


class TimeoutException(Exception):
    pass


def pretty_log(src, indent=0, invert=False):
    """ Make log more readable and awesome
    The main application is using instead of json.dumps().

    :param src: dictionary with data, list of dicts
                can be also used for strings or lists of strings,
                but it makes no sense.
                Note: Indent for list by default is +3. If you want to call
                pretty_log for list , call it with indent=-3 for 0,
                indent=-3+1 for 1 and etc.
    :param indent: int
    :param invert: Swaps first and second columns. Can be used ONLY
     with one levels dictionary
    :return: formatted string with result, can be used in log

    """

    result = ''
    templates = ["\n{indent}{item:{len}}{value}" if not invert else
                 "\n{indent}{value:{len}}{item}",
                 "\n{indent}{item}:",
                 '\n{indent}{value}']

    if src and isinstance(src, dict):
        max_len = len(max(src.values() if invert else src.keys(),
                          key=lambda x: len(str(x))))
        for key, value in src.items():
            if (isinstance(value, dict) and value) or \
                    isinstance(value, list):
                result += templates[1].format(indent=' ' * indent, item=key)
                result += pretty_log(value, indent + 3)
            else:
                result += templates[0].format(indent=' ' * indent,
                                              item=key,
                                              value=str(value),
                                              len=max_len + 5)

    elif src and isinstance(src, list):
        for el in src:
            if (isinstance(el, dict) and el) or isinstance(el, list):
                res = pretty_log(el, indent + 3)
            else:
                res = templates[2].format(indent=' ' * (indent + 3),
                                          value=str(el))
            result += res[:indent + 2] + '-' + res[indent + 3:]
    return result


@logwrap
def get_config_template(template_name):
    """Get content of yaml file as dictionary.

    :param template_name: a string of name yaml file
    :return: a dictionary with configuration data
    """
    import fuelweb_test
    template = os.path.join(os.path.dirname(fuelweb_test.__file__),
                            'config_templates/{0}.yaml'.format(template_name))
    if os.path.exists(template):
        with open(template) as template_file:
            return yaml.load(template_file)


@logwrap
def get_ini_config(data):
    """Get a data of configuration file.

    :param data: a file object
    :return: a ConfigParser object
    """
    config = configparser.ConfigParser()
    config.readfp(data)
    return config


@logwrap
def check_config(conf, conf_name, section, option, value):
    """Check existence of parameter with a proper value
    or its absence in configuration file.

    :param conf: a file object
    :param conf_name: a string of full file path
    :param section: a string of section name in configuration file
    :param option: a string of option name in configuration file
    :param value: None or a string of value in configuration file
    """
    if value is None:
        if conf.has_section(section) and conf.has_option(section, option):
            current_value = conf.get(section, option)
            raise Exception('The option "{0}" of section "{1}" should be '
                            'absent but actually has value "{2}" '
                            'in config file "{3}": FAIL'.format(option,
                                                                section,
                                                                current_value,
                                                                conf_name))
        logger.debug('Expected that the option "{0}" of section "{1}" is '
                     'absent in config file "{2}": SUCCESS'.format(option,
                                                                   section,
                                                                   conf_name))
    else:
        if not conf.has_section(section) and section != 'DEFAULT':
            raise Exception('The section "{0}" is absent in '
                            'config file "{1}": FAIL'.format(section,
                                                             conf_name))
        if not conf.has_option(section, option):
            raise Exception('The option "{0}" of section "{1}" is absent '
                            'in config file "{2}": FAIL'.format(option,
                                                                section,
                                                                conf_name))
        current_value = conf.get(section, option)
        asserts.assert_equal(current_value,
                             value,
                             'Expected that the option "{0}" has value '
                             '"{1}" in config file {2} but actually has '
                             'value "{3}": FAIL'.format(option,
                                                        value,
                                                        conf_name,
                                                        current_value))
        logger.debug('The config file "{0}" contains '
                     'the correct value "{1}" of option "{2}" '
                     'in section "{3}": SUCCESS'.format(conf_name,
                                                        value,
                                                        option,
                                                        section))


@logwrap
def get_process_uptime(remote, process_name):
    """Get process uptime.

    :param remote: SSHClient to node
    :param process_name: a string of process name
    :return: a int value of process uptime in seconds
    """
    cmd = "ps hf -opid -C {0} | awk '{{print $1; exit}}'".format(process_name)
    parent_pid = remote.execute(cmd)['stdout']
    asserts.assert_not_equal(parent_pid,
                             [],
                             "No such process "
                             "with name {0}".format(process_name))
    parent_pid = parent_pid[0].replace('\n', '')
    cmd = "ps -p {0} -o etime= | awk '{{print $1}}'".format(parent_pid)
    ps_output = remote.execute(cmd)['stdout'][0].replace('\n', '')
    ps_output = ps_output.split(':')
    uptime = 0
    time_factor = 1
    for i in xrange(1, len(ps_output) + 1):
        uptime += int(ps_output[-i]) * time_factor
        time_factor *= 60
    return uptime


def get_package_version(remote_admin, package, income=None):
    if income:
        cmd_version = ('rpm '
                       '-qp {0} --queryformat '
                       '"%{{VERSION}} %{{RELEASE}}"'.format(package))
    else:
        cmd_version = ('rpm '
                       '-q {0} --queryformat '
                       '"%{{VERSION}} %{{RELEASE}}"'.format(package))
    result = remote_admin.execute(cmd_version)
    logger.debug('Command {0} execution result {1}'.format(
        cmd_version, result))
    if result['exit_code'] != 0:
        asserts.assert_true('not installed' in ''.join(result['stdout']),
                            'Command {0} fails by unexpected '
                            'reason {1}'.format(cmd_version, result))
        return None
    return ''.join(result['stdout']).strip()


def compare_packages_version(remote, package_name, income_package_name):
    income_release, income_version = get_package_version(
        remote, income_package_name, income=True).split(' ')
    if not get_package_version(remote, package_name):
        return True
    installed_release, installed_version = get_package_version(
        remote, package_name).split(' ')
    if not version.LooseVersion(income_release) == version.LooseVersion(
            installed_release):
        raise exceptions.PackageVersionError(
            package=income_package_name, version=income_release)
    if version.LooseVersion(installed_version) >= version.LooseVersion(
            income_version):
        raise exceptions.PackageVersionError(
            package=income_package_name, version=income_version)
    else:
        return True


def erase_data_from_hdd(remote,
                        device=None,
                        mount_point=None,
                        source="/dev/zero",
                        block_size=512,
                        blocks_from_start=2 * 1024 * 8,
                        blocks_from_end=2 * 1024 * 8):
    """Erases data on "device" using "dd" utility.

    :param remote: devops.SSHClient, remote to node
    :param device: str, block device which should be corrupted. If none -
       drive mounted at "mount_point" will be used for erasing
    :param mount_point: str, mount point for auto-detecting drive for erasing
    :param source: str, block device or file that will be used as source for
       "dd", default - /dev/zero
    :param block_size: int, block size which will be pass to "dd"
    :param blocks_from_start: int, count of blocks which will be erased from
       the beginning of the hard drive. Default - 16,384 (with bs=512 - 8MB)
    :param blocks_from_end: int, count of blocks which will be erased from
       the end of the hard drive. Default - 16,384 (with bs=512 - 8MB)
    :raises Exception: if return code of any of commands is not 0
    """
    if not device:
        asserts.assert_is_not_none(
            mount_point,
            "Mount point is not defined, will do nothing")
        device = remote.execute(
            "awk '$2 == \"{mount_point}\" {{print $1}}' /proc/mounts".format(
                mount_point=mount_point)
        )['stdout'][0]
    # get block device for partition
    try:
        device = re.findall(r"(/dev/[a-z]+)", device)[0]
    except IndexError:
        logger.error("Can not find any block device in output! "
                     "Output is:'{}'".format(device))
    commands = []
    logger.debug("Boot sector of device '{}' will be erased".format(device))
    if blocks_from_start > 0:
        commands.append(
            "dd bs={block_size} if={source} of={device} "
            "count={blocks_from_start}".format(
                block_size=block_size,
                source=source,
                device=device,
                blocks_from_start=blocks_from_start)
        )
    if blocks_from_end > 0:
        commands.append(
            "dd bs={block_size} if={source} of={device} "
            "count={blocks_from_end} "
            "seek=$((`blockdev --getsz {device}` - {seek}))".format(
                block_size=block_size,
                source=source,
                device=device,
                blocks_from_end=blocks_from_end,
                seek=block_size * blocks_from_end)
        )
    commands.append("sync")

    for cmd in commands:
        run_on_remote(remote, cmd)


@logwrap
def fill_space(ip, file_dir, size):
    """Allocates space to some file in the specified directory
     on the specified node

    :param ip: the ip of the node
    :param file_dir: the specified directory
    :param size: the amount of space in Mb
    """
    file_name = "test_data"
    file_path = os.path.join(file_dir, file_name)
    SSHManager().execute_on_remote(
        ip=ip,
        cmd='fallocate -l {0}M {1}'.format(size, file_path),
        err_msg="The file {0} was not allocated".format(file_name))


@logwrap
def get_ceph_partitions(ip, device, fs_type="xfs"):
    # Moved from checkers.py for improvement of code
    ret = SSHManager().check_call(
        ip=ip,
        cmd="parted {device} print | grep {type}".format(device=device,
                                                         type=fs_type)
    )['stdout']
    if not ret:
        logger.error(
            "Partition not present! {partitions}: ".format(
                partitions=SSHManager().check_call(
                    ip=ip, cmd="parted {device} print")))
        raise Exception()
    logger.debug("Partitions: {part}".format(part=ret))
    return ret


@logwrap
def get_mongo_partitions(ip, device):
    # Moved from checkers.py for improvement of code
    ret = SSHManager().check_call(
        ip=ip,
        cmd="lsblk | grep {device} | awk {size}".format(
            device=device,
            size=re.escape('{print $4}'))
    )['stdout']
    if not ret:
        logger.error(
            "Partition not present! {partitions}: ".format(
                partitions=SSHManager().check_call(
                    ip=ip, cmd="parted {device} print")))
        raise Exception()
    logger.debug("Partitions: {part}".format(part=ret))
    return ret


@logwrap
def upload_tarball(ip, tar_path, tar_target):
    # Moved from checkers.py for improvement of code
    assert_true(tar_path, "Source path for uploading 'tar_path' is empty, "
                "please check test settings!")
    if os.path.splitext(tar_path)[1] not in [".tar", ".lrz", ".fp", ".rpm"]:
        raise Exception("Wrong archive type!")
    try:
        logger.info("Start to upload tar file")
        SSHManager().upload_to_remote(
            ip=ip,
            source=tar_path,
            target=tar_target
        )
        logger.info('File {} was uploaded on master'.format(tar_path))
    except Exception:
        logger.error('Failed to upload file')
        logger.error(traceback.format_exc())


@logwrap
def install_plugin_check_code(ip, plugin, exit_code=0):
    # Moved from checkers.py for improvement of code
    cmd = "cd /var && fuel plugins --install {0} ".format(plugin)
    chan, _, stderr, _ = SSHManager().execute_async_on_remote(
        ip=ip,
        cmd=cmd
    )
    logger.debug('Try to read status code from chain...')
    assert_equal(
        chan.recv_exit_status(), exit_code,
        'Install script fails with next message {0}'.format(''.join(stderr)))


@logwrap
def get_package_versions_from_node(ip, name, os_type):
    # Moved from checkers.py for improvement of code
    if os_type and 'Ubuntu' in os_type:
        cmd = "dpkg-query -W -f='${Version}' %s" % name
    else:
        cmd = "rpm -q {0}".format(name)
    try:
        result = ''.join(SSHManager().execute(ip, cmd)['stdout'])
        return result.strip()
    except Exception:
        logger.error(traceback.format_exc())
        raise


@logwrap
def get_file_size(ip, file_name, file_path):
    # Moved from checkers.py for improvement of code
    file_size = SSHManager().execute(
        ip, 'stat -c "%s" {0}/{1}'.format(file_path, file_name))
    assert_equal(
        int(file_size['exit_code']), 0, "Failed to get '{0}/{1}' file stats on"
                                        " remote node".format(file_path,
                                                              file_name))
    return int(file_size['stdout'][0].rstrip())


@logwrap
def get_quantity_of_numa(ip):
    """Get number of NUMA nodes that are contained on remote node

    :param remote: node IP
    :return: int, count of available NUMA nodes on the node
    """

    numa = int(SSHManager().check_call(
        ip=ip,
        cmd="lstopo | grep NUMANode| wc -l"
    )['stdout'][0])

    if not numa:
        logger.debug("There are no NUMA nodes on {0}".format(ip))
    else:
        logger.debug("There is {0} NUMA node(s) on {1}".format(numa, ip))
    return numa


@logwrap
def dict_merge(a, b):
    """ Recursively merges dict's.

    Not just simple a['key'] = b['key'], if both a and b have a key
    who's value is a dict then dict_merge is called on both values
    and the result stored in the returned dictionary.
    """
    if not isinstance(b, dict):
        return copy.deepcopy(b)
    result = copy.deepcopy(a)
    for k, v in b.iteritems():
        if k in result and isinstance(result[k], dict):
            result[k] = dict_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result
