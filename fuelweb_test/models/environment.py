#    Copyright 2013 Mirantis, Inc.
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

import re
import subprocess
import time

from devops.error import TimeoutError
from devops.helpers.helpers import _tcp_ping
from devops.helpers.helpers import _wait
from devops.helpers.helpers import wait
from devops.helpers.ntp import sync_time
from devops.models import Environment
from keystoneclient import exceptions
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_true
import six

from fuelweb_test.helpers.decorators import revert_info
from fuelweb_test.helpers.decorators import update_rpm_packages
from fuelweb_test.helpers.decorators import upload_manifests
from fuelweb_test.helpers.metaclasses import SingletonMeta
from fuelweb_test.helpers.eb_tables import Ebtables
from fuelweb_test.helpers.fuel_actions import AdminActions
from fuelweb_test.helpers.fuel_actions import BaseActions
from fuelweb_test.helpers.fuel_actions import CobblerActions
from fuelweb_test.helpers.fuel_actions import NailgunActions
from fuelweb_test.helpers.fuel_actions import PostgresActions
from fuelweb_test.helpers.fuel_actions import NessusActions
from fuelweb_test.helpers.fuel_actions import FuelBootstrapCliActions
from fuelweb_test.helpers.ssh_manager import SSHManager
from fuelweb_test.helpers.utils import erase_data_from_hdd
from fuelweb_test.helpers.utils import TimeStat
from fuelweb_test.helpers import multiple_networks_hacks
from fuelweb_test.models.fuel_web_client import FuelWebClient
from fuelweb_test.models.collector_client import CollectorClient
from fuelweb_test import settings
from fuelweb_test.settings import iface_alias
from fuelweb_test import logwrap
from fuelweb_test import logger


@six.add_metaclass(SingletonMeta)
class EnvironmentModel(object):
    """EnvironmentModel."""  # TODO documentation

    def __init__(self, config=None):
        if not hasattr(self, "_virt_env"):
            self._virt_env = None
        if not hasattr(self, "_fuel_web"):
            self._fuel_web = None
        self._config = config
        self.ssh_manager = SSHManager()
        self.ssh_manager.initialize(
            self.get_admin_node_ip(),
            login=settings.SSH_CREDENTIALS['login'],
            password=settings.SSH_CREDENTIALS['password']
        )
        self.admin_actions = AdminActions()
        self.base_actions = BaseActions()
        self.cobbler_actions = CobblerActions()
        self.nailgun_actions = NailgunActions()
        self.postgres_actions = PostgresActions()
        self.fuel_bootstrap_actions = FuelBootstrapCliActions()

    @property
    def fuel_web(self):
        if self._fuel_web is None:
            self._fuel_web = FuelWebClient(self)
        return self._fuel_web

    def __repr__(self):
        klass, obj_id = type(self), hex(id(self))
        if getattr(self, '_fuel_web'):
            ip = self.fuel_web.admin_node_ip
        else:
            ip = None
        return "[{klass}({obj_id}), ip:{ip}]".format(klass=klass,
                                                     obj_id=obj_id,
                                                     ip=ip)

    @property
    def admin_node_ip(self):
        return self.fuel_web.admin_node_ip

    @property
    def collector(self):
        return CollectorClient(settings.ANALYTICS_IP, 'api/v1/json')

    @logwrap
    def add_syslog_server(self, cluster_id, port=5514):
        self.fuel_web.add_syslog_server(
            cluster_id, self.d_env.router(), port)

    def bootstrap_nodes(self, devops_nodes, timeout=settings.BOOTSTRAP_TIMEOUT,
                        skip_timesync=False):
        """Lists registered nailgun nodes
        Start vms and wait until they are registered on nailgun.
        :rtype : List of registered nailgun nodes
        """
        # self.dhcrelay_check()

        for node in devops_nodes:
            logger.info("Bootstrapping node: {}".format(node.name))
            node.start()
            # TODO(aglarendil): LP#1317213 temporary sleep
            # remove after better fix is applied
            time.sleep(5)

        with TimeStat("wait_for_nodes_to_start_and_register_in_nailgun"):
            wait(lambda: all(self.nailgun_nodes(devops_nodes)), 15, timeout)

        if not skip_timesync:
            self.sync_time()
        return self.nailgun_nodes(devops_nodes)

    def sync_time(self, nodes_names=None, skip_sync=False):
        if nodes_names is None:
            roles = ['fuel_master', 'fuel_slave']
            nodes_names = [node.name for node in self.d_env.get_nodes()
                           if node.role in roles and
                           node.driver.node_active(node)]
        logger.info("Please wait while time on nodes: {0} "
                    "will be synchronized"
                    .format(', '.join(sorted(nodes_names))))
        new_time = sync_time(self.d_env, nodes_names, skip_sync)
        for name in sorted(new_time):
            logger.info("New time on '{0}' = {1}".format(name, new_time[name]))

    @logwrap
    def get_admin_node_ip(self):
        return str(
            self.d_env.nodes(
            ).admin.get_ip_address_by_network_name(
                self.d_env.admin_net))

    @logwrap
    def get_ebtables(self, cluster_id, devops_nodes):
        return Ebtables(self.get_target_devs(devops_nodes),
                        self.fuel_web.client.get_cluster_vlans(cluster_id))

    def get_keys(self, node, custom=None, build_images=None,
                 iso_connect_as='cdrom'):
        params = {
            'device_label': settings.ISO_LABEL,
            'iface': iface_alias('eth0'),
            'ip': node.get_ip_address_by_network_name(
                self.d_env.admin_net),
            'mask': self.d_env.get_network(
                name=self.d_env.admin_net).ip.netmask,
            'gw': self.d_env.router(),
            'hostname': ''.join((settings.FUEL_MASTER_HOSTNAME,
                                 settings.DNS_SUFFIX)),
            'nat_interface': self.d_env.nat_interface,
            'nameserver': settings.DNS,
            'showmenu': 'yes' if settings.SHOW_FUELMENU else 'no',
            'wait_for_external_config': 'yes',
            'build_images': '1' if build_images else '0'
        }
        # TODO(akostrikov) add tests for menu items/kernel parameters
        # TODO(akostrikov) refactor it.
        if iso_connect_as == 'usb':
            keys = (
                "<Wait>\n"  # USB boot uses boot_menu=yes for master node
                "<F12>\n"
                "2\n"
            )
        else:  # cdrom is default
            keys = (
                "<Wait>\n"
                "<Wait>\n"
                "<Wait>\n"
            )

        keys += (
            "<Esc>\n"
            "<Wait>\n"
            "vmlinuz initrd=initrd.img"
            " inst.ks=cdrom:LABEL=%(device_label)s:/ks.cfg"
            " inst.repo=cdrom:LABEL=%(device_label)s:/"
            " ip=%(ip)s::%(gw)s:%(mask)s:%(hostname)s"
            ":%(iface)s:off::: nameserver=%(nameserver)s"
            " showmenu=%(showmenu)s\n"
            " wait_for_external_config=%(wait_for_external_config)s"
            " build_images=%(build_images)s\n"
            " <Enter>\n"
        ) % params
        return keys

    @staticmethod
    def get_target_devs(devops_nodes):
        return [
            interface.target_dev for interface in [
                val for var in map(lambda node: node.interfaces, devops_nodes)
                for val in var]]

    @property
    def d_env(self):
        if self._virt_env is None:
            if not self._config:
                try:
                    return Environment.get(name=settings.ENV_NAME)
                except Exception:
                    self._virt_env = Environment.describe_environment(
                        boot_from=settings.ADMIN_BOOT_DEVICE)
                    self._virt_env.define()
            else:
                try:
                    return Environment.get(name=self._config[
                        'template']['devops_settings']['env_name'])
                except Exception:
                    self._virt_env = Environment.create_environment(
                        full_config=self._config)
                    self._virt_env.define()
        return self._virt_env

    def resume_environment(self):
        self.d_env.resume()
        admin = self.d_env.nodes().admin

        self.ssh_manager.clean_all_connections()

        try:
            admin.await(self.d_env.admin_net, timeout=30, by_port=8000)
        except Exception as e:
            logger.warning("From first time admin isn't reverted: "
                           "{0}".format(e))
            admin.destroy()
            logger.info('Admin node was destroyed. Wait 10 sec.')
            time.sleep(10)

            admin.start()
            logger.info('Admin node started second time.')
            self.d_env.nodes().admin.await(self.d_env.admin_net)
            self.set_admin_ssh_password()
            self.admin_actions.wait_for_fuel_ready(timeout=600)

            # set collector address in case of admin node destroy
            if settings.FUEL_STATS_ENABLED:
                self.nailgun_actions.set_collector_address(
                    settings.FUEL_STATS_HOST,
                    settings.FUEL_STATS_PORT,
                    settings.FUEL_STATS_SSL)
                # Restart statsenderd in order to apply new collector address
                self.nailgun_actions.force_fuel_stats_sending()
                self.fuel_web.client.send_fuel_stats(enabled=True)
                logger.info('Enabled sending of statistics to {0}:{1}'.format(
                    settings.FUEL_STATS_HOST, settings.FUEL_STATS_PORT
                ))
        self.set_admin_ssh_password()
        self.admin_actions.wait_for_fuel_ready()

    def make_snapshot(self, snapshot_name, description="", is_make=False):
        if settings.MAKE_SNAPSHOT or is_make:
            self.d_env.suspend()
            time.sleep(10)

            self.d_env.snapshot(snapshot_name, force=True,
                                description=description)
            revert_info(snapshot_name, self.get_admin_node_ip(), description)

        if settings.FUEL_STATS_CHECK:
            self.resume_environment()

    def nailgun_nodes(self, devops_nodes):
        return [self.fuel_web.get_nailgun_node_by_devops_node(node)
                for node in devops_nodes]

    def check_slaves_are_ready(self):
        devops_nodes = [node for node in self.d_env.nodes().slaves
                        if node.driver.node_active(node)]
        # Bug: 1455753
        time.sleep(30)

        for node in devops_nodes:
            try:
                wait(lambda:
                     self.fuel_web.get_nailgun_node_by_devops_node(
                         node)['online'], timeout=60 * 6)
            except TimeoutError:
                raise TimeoutError(
                    "Node {0} does not become online".format(node.name))
        return True

    def revert_snapshot(self, name, skip_timesync=False,
                        skip_slaves_check=False):
        if not self.d_env.has_snapshot(name):
            return False

        logger.info('We have snapshot with such name: {:s}'.format(name))

        logger.info("Reverting the snapshot '{0}' ....".format(name))
        self.d_env.revert(name)

        logger.info("Resuming the snapshot '{0}' ....".format(name))
        self.resume_environment()

        if not skip_timesync:
            self.sync_time()
        try:
            _wait(self.fuel_web.client.get_releases,
                  expected=EnvironmentError, timeout=300)
        except exceptions.Unauthorized:
            self.set_admin_keystone_password()
            self.fuel_web.get_nailgun_version()

        if not skip_slaves_check:
            _wait(lambda: self.check_slaves_are_ready(), timeout=60 * 6)
        return True

    def set_admin_ssh_password(self):
        new_login = settings.SSH_CREDENTIALS['login']
        new_password = settings.SSH_CREDENTIALS['password']
        try:
            self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd='date'
            )
            logger.debug('Accessing admin node using SSH: SUCCESS')
        except Exception:
            logger.debug('Accessing admin node using SSH credentials:'
                         ' FAIL, trying to change password from default')
            self.ssh_manager.initialize(
                admin_ip=self.ssh_manager.admin_ip,
                login='root',
                password='r00tme'
            )
            self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd='echo -e "{1}\\n{1}" | passwd {0}'.format(new_login,
                                                              new_password)
            )
            self.ssh_manager.initialize(
                admin_ip=self.ssh_manager.admin_ip,
                login=new_login,
                password=new_password
            )
            self.ssh_manager.update_connection(
                ip=self.ssh_manager.admin_ip,
                login=new_login,
                password=new_password
            )
            logger.debug("Admin node password has changed.")
        logger.info("Admin node login name: '{0}' , password: '{1}'".
                    format(new_login, new_password))

    def set_admin_keystone_password(self):
        try:
            self.fuel_web.client.get_releases()
        # TODO(akostrikov) CENTOS7 except exceptions.Unauthorized:
        except:
            self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd='fuel user --newpass {0} --change-password'.format(
                    settings.KEYSTONE_CREDS['password'])
            )
            logger.info(
                'New Fuel UI (keystone) username: "{0}", password: "{1}"'
                .format(settings.KEYSTONE_CREDS['username'],
                        settings.KEYSTONE_CREDS['password']))

    def insert_cdrom_tray(self):
        # This is very rude implementation and it SHOULD be changes after
        # implementation this feature in fuel-devops
        name = "{}_{}".format(settings.ENV_NAME, self.d_env.nodes().admin.name)
        name_size = 80
        if len(name) > name_size:
            hash_str = str(hash(name))
            name = (hash_str + name)[:name_size]

        cmd = """EDITOR="sed -i s/tray=\\'open\\'//" virsh edit {}""".format(
            name)
        subprocess.check_call(cmd, shell=True)

    def reinstall_master_node(self):
        """Erase boot sector and run setup_environment"""
        with self.d_env.get_admin_remote() as remote:
            erase_data_from_hdd(remote, mount_point='/boot')
            remote.execute("/sbin/shutdown")
        self.d_env.nodes().admin.destroy()
        self.insert_cdrom_tray()
        self.setup_environment()

    def setup_environment(self, custom=settings.CUSTOM_ENV,
                          build_images=settings.BUILD_IMAGES,
                          iso_connect_as=settings.ADMIN_BOOT_DEVICE,
                          security=settings.SECURITY_TEST,
                          force_ssl=settings.FORCE_HTTPS_MASTER_NODE):
        # Create environment and start the Fuel master node
        admin = self.d_env.nodes().admin
        self.d_env.start([admin])

        logger.info("Waiting for admin node to start up")
        wait(lambda: admin.driver.node_active(admin), 60)
        logger.info("Proceed with installation")
        # update network parameters at boot screen
        admin.send_keys(self.get_keys(admin, custom=custom,
                                      build_images=build_images,
                                      iso_connect_as=iso_connect_as))
        if settings.SHOW_FUELMENU:
            self.wait_for_fuelmenu()
        else:
            self.wait_for_provisioning()

        self.set_admin_ssh_password()

        self.wait_for_external_config()
        if custom:
            self.setup_customisation()
        if security:
            nessus_node = NessusActions(self.d_env)
            nessus_node.add_nessus_node()
        # wait while installation complete

        self.admin_actions.modify_configs(self.d_env.router())
        self.kill_wait_for_external_config()
        self.wait_bootstrap()

        if settings.UPDATE_FUEL:
            # Update Ubuntu packages
            self.admin_actions.upload_packages(
                local_packages_dir=settings.UPDATE_FUEL_PATH,
                centos_repo_path=None,
                ubuntu_repo_path=settings.LOCAL_MIRROR_UBUNTU)

        self.admin_actions.wait_for_fuel_ready()
        time.sleep(10)
        self.set_admin_keystone_password()
        self.sync_time(['admin'])
        if settings.UPDATE_MASTER:
            if settings.UPDATE_FUEL_MIRROR:
                for i, url in enumerate(settings.UPDATE_FUEL_MIRROR):
                    conf_file = '/etc/yum.repos.d/temporary-{}.repo'.format(i)
                    cmd = ("echo -e"
                           " '[temporary-{0}]\nname="
                           "temporary-{0}\nbaseurl={1}/"
                           "\ngpgcheck=0\npriority="
                           "1' > {2}").format(i, url, conf_file)

                    self.ssh_manager.execute(
                        ip=self.ssh_manager.admin_ip,
                        cmd=cmd
                    )
            self.admin_install_updates()
        if settings.MULTIPLE_NETWORKS:
            self.describe_other_admin_interfaces(admin)
        self.nailgun_actions.set_collector_address(
            settings.FUEL_STATS_HOST,
            settings.FUEL_STATS_PORT,
            settings.FUEL_STATS_SSL)
        # Restart statsenderd to apply settings(Collector address)
        self.nailgun_actions.force_fuel_stats_sending()
        if settings.FUEL_STATS_ENABLED:
            self.fuel_web.client.send_fuel_stats(enabled=True)
            logger.info('Enabled sending of statistics to {0}:{1}'.format(
                settings.FUEL_STATS_HOST, settings.FUEL_STATS_PORT
            ))
        if settings.PATCHING_DISABLE_UPDATES:
            cmd = "find /etc/yum.repos.d/ -type f -regextype posix-egrep" \
                  " -regex '.*/mos[0-9,\.]+\-(updates|security).repo' | " \
                  "xargs -n1 -i sed '$aenabled=0' -i {}"
            self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd=cmd
            )
        if settings.DISABLE_OFFLOADING:
            logger.info(
                '========================================'
                'Applying workaround for bug #1526544'
                '========================================'
            )
            # Disable TSO offloading for every network interface
            # that is not virtual (loopback, bridges, etc)
            ifup_local = (
                """#!/bin/bash\n"""
                """if [[ -z "${1}" ]]; then\n"""
                """  exit\n"""
                """fi\n"""
                """devpath=$(readlink -m /sys/class/net/${1})\n"""
                """if [[ "${devpath}" == /sys/devices/virtual/* ]]; then\n"""
                """  exit\n"""
                """fi\n"""
                """ethtool -K ${1} tso off\n"""
            )
            cmd = (
                "echo -e '{0}' | sudo tee /sbin/ifup-local;"
                "sudo chmod +x /sbin/ifup-local;"
            ).format(ifup_local)
            self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd=cmd
            )
            cmd = (
                'for ifname in $(ls /sys/class/net); do '
                'sudo /sbin/ifup-local ${ifname}; done'
            )
            self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd=cmd
            )
            # Log interface settings
            cmd = (
                'for ifname in $(ls /sys/class/net); do '
                '([[ $(readlink -e /sys/class/net/${ifname}) == '
                '/sys/devices/virtual/* ]] '
                '|| ethtool -k ${ifname}); done'
            )
            result = self.ssh_manager.execute_on_remote(
                ip=self.ssh_manager.admin_ip,
                cmd=cmd
            )
            logger.debug('Offloading settings:\n{0}\n'.format(
                         ''.join(result['stdout'])))
            if force_ssl:
                self.enable_force_https(self.ssh_manager.admin_ip)

    @logwrap
    def enable_force_https(self, admin_node_ip):
        cmd = """
        echo -e '"SSL":\n  "force_https": "true"' >> /etc/fuel/astute.yaml
        """
        self.ssh_manager.execute_on_remote(admin_node_ip, cmd)
        cmd = "find / -name \"nginx_services.pp\""
        puppet_manifest = \
            self.ssh_manager.execute_on_remote(
                admin_node_ip, cmd)['stdout'][0].strip()
        cmd = 'puppet apply {0}'.format(puppet_manifest)
        self.ssh_manager.execute_on_remote(admin_node_ip, cmd)
        cmd = """
        systemctl status nginx.service |
        awk 'match($0, /\s+Active:.*\((\w+)\)/, a) {print a[1]}'
        """
        wait(lambda: (
             self.ssh_manager.execute_on_remote(
                 admin_node_ip, cmd)['stdout'][0] != 'dead'), interval=10,
             timeout=30)

    # pylint: disable=no-self-use
    @update_rpm_packages
    @upload_manifests
    def setup_customisation(self):
        logger.info('Installing custom packages/manifests '
                    'before master node bootstrap...')
    # pylint: enable=no-self-use

    @logwrap
    def wait_for_provisioning(self,
                              timeout=settings.WAIT_FOR_PROVISIONING_TIMEOUT):
        _wait(lambda: _tcp_ping(
            self.d_env.nodes(
            ).admin.get_ip_address_by_network_name
            (self.d_env.admin_net), 22), timeout=timeout)

    @logwrap
    def wait_for_fuelmenu(self,
                          timeout=settings.WAIT_FOR_PROVISIONING_TIMEOUT):

        def check_ssh_connection():
            """Try to close fuelmenu and check ssh connection"""
            try:
                _tcp_ping(
                    self.d_env.nodes(
                    ).admin.get_ip_address_by_network_name
                    (self.d_env.admin_net), 22)
            except Exception:
                #  send F8 trying to exit fuelmenu
                self.d_env.nodes().admin.send_keys("<F8>\n")
                return False
            return True

        wait(check_ssh_connection, interval=30, timeout=timeout,
             timeout_msg="Fuelmenu hasn't appeared during allocated timeout")

    @logwrap
    def wait_for_external_config(self, timeout=120):
        check_cmd = 'pkill -0 -f wait_for_external_config'

        wait(
            lambda: self.ssh_manager.execute(
                ip=self.ssh_manager.admin_ip,
                cmd=check_cmd)['exit_code'] == 0, timeout=timeout)

    @logwrap
    def kill_wait_for_external_config(self):
        kill_cmd = 'pkill -f "^wait_for_external_config"'
        check_cmd = 'pkill -0 -f "^wait_for_external_config"; [[ $? -eq 1 ]]'
        self.ssh_manager.execute_on_remote(
            ip=self.ssh_manager.admin_ip,
            cmd=kill_cmd
        )
        self.ssh_manager.execute_on_remote(
            ip=self.ssh_manager.admin_ip,
            cmd=check_cmd
        )

    def wait_bootstrap(self):
        logger.info("Waiting while bootstrapping is in progress")
        log_path = "/var/log/puppet/bootstrap_admin_node.log"
        logger.info("Running bootstrap (timeout: {0})".format(
            float(settings.ADMIN_NODE_BOOTSTRAP_TIMEOUT)))
        with TimeStat("admin_node_bootsrap_time", is_uniq=True):
            wait(
                lambda: self.ssh_manager.execute(
                    ip=self.ssh_manager.admin_ip,
                    cmd="grep 'Fuel node deployment' '{:s}'".format(log_path)
                )['exit_code'] == 0,
                timeout=(float(settings.ADMIN_NODE_BOOTSTRAP_TIMEOUT))
            )
        result = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd="grep 'Fuel node deployment "
            "complete' '{:s}'".format(log_path))['exit_code']
        if result != 0:
            raise Exception('Fuel node deployment failed.')
        self.bootstrap_image_check()

    def dhcrelay_check(self):
        # CentOS 7 is pretty stable with admin iface.
        # TODO(akostrikov) refactor it.
        iface = iface_alias('eth0')
        command = "dhcpcheck discover " \
                  "--ifaces {iface} " \
                  "--repeat 3 " \
                  "--timeout 10".format(iface=iface)

        out = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd=command
        )['stdout']

        assert_true(self.get_admin_node_ip() in "".join(out),
                    "dhcpcheck doesn't discover master ip")

    def bootstrap_image_check(self):
        fuel_settings = self.admin_actions.get_fuel_settings()
        if fuel_settings['BOOTSTRAP']['flavor'].lower() != 'ubuntu':
            logger.warning('Default image for bootstrap '
                           'is not based on Ubuntu!')
            return

        bootstrap_images = self.ssh_manager.execute_on_remote(
            ip=self.ssh_manager.admin_ip,
            cmd='fuel-bootstrap --quiet list'
        )['stdout']
        assert_true(any('active' in line for line in bootstrap_images),
                    'Ubuntu bootstrap image wasn\'t built and activated! '
                    'See logs in /var/log/fuel-bootstrap-image-build.log '
                    'for details.')

    def admin_install_pkg(self, pkg_name):
        """Install a package <pkg_name> on the admin node"""
        remote_status = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd="rpm -q {0}'".format(pkg_name)
        )
        if remote_status['exit_code'] == 0:
            logger.info("Package '{0}' already installed.".format(pkg_name))
        else:
            logger.info("Installing package '{0}' ...".format(pkg_name))
            remote_status = self.ssh_manager.execute(
                ip=self.ssh_manager.admin_ip,
                cmd="yum -y install {0}".format(pkg_name)
            )
            logger.info("Installation of the package '{0}' has been"
                        " completed with exit code {1}"
                        .format(pkg_name, remote_status['exit_code']))
        return remote_status['exit_code']

    def admin_run_service(self, service_name):
        """Start a service <service_name> on the admin node"""

        self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd="service {0} start".format(service_name)
        )
        remote_status = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd="service {0} status".format(service_name)
        )
        if any('running...' in status for status in remote_status['stdout']):
            logger.info("Service '{0}' is running".format(service_name))
        else:
            logger.info("Service '{0}' failed to start"
                        " with exit code {1} :\n{2}"
                        .format(service_name,
                                remote_status['exit_code'],
                                remote_status['stdout']))

    # Execute yum updates
    # If updates installed,
    # then `bootstrap_admin_node.sh;`
    def admin_install_updates(self):
        logger.info('Searching for updates..')
        update_command = 'yum clean expire-cache; yum update -y'

        update_result = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd=update_command
        )

        logger.info('Result of "{1}" command on master node: '
                    '{0}'.format(update_result, update_command))
        assert_equal(int(update_result['exit_code']), 0,
                     'Packages update failed, '
                     'inspect logs for details')

        # Check if any packets were updated and update was successful
        for str_line in update_result['stdout']:
            match_updated_count = re.search("Upgrade(?:\s*)(\d+).*Package",
                                            str_line)
            if match_updated_count:
                updates_count = match_updated_count.group(1)
            match_complete_message = re.search("(Complete!)", str_line)
            match_no_updates = re.search("No Packages marked for Update",
                                         str_line)

        if (not match_updated_count or match_no_updates)\
                and not match_complete_message:
            logger.warning('No updates were found or update was incomplete.')
            return
        logger.info('{0} packet(s) were updated'.format(updates_count))

        cmd = 'bootstrap_admin_node.sh;'

        result = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd=cmd
        )
        logger.info('Result of "{1}" command on master node: '
                    '{0}'.format(result, cmd))
        assert_equal(int(result['exit_code']), 0,
                     'bootstrap failed, '
                     'inspect logs for details')

    # Modifies a resolv.conf on the Fuel master node and returns
    # its original content.
    # * adds 'nameservers' at start of resolv.conf if merge=True
    # * replaces resolv.conf with 'nameservers' if merge=False
    def modify_resolv_conf(self, nameservers=None, merge=True):
        if nameservers is None:
            nameservers = []

        resolv_conf = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd='cat /etc/resolv.conf'
        )
        assert_equal(0, resolv_conf['exit_code'],
                     'Executing "{0}" on the admin node has failed with: {1}'
                     .format('cat /etc/resolv.conf', resolv_conf['stderr']))
        if merge:
            nameservers.extend(resolv_conf['stdout'])
        resolv_keys = ['search', 'domain', 'nameserver']
        resolv_new = "".join('{0}\n'.format(ns) for ns in nameservers
                             if any(x in ns for x in resolv_keys))
        logger.debug('echo "{0}" > /etc/resolv.conf'.format(resolv_new))
        echo_cmd = 'echo "{0}" > /etc/resolv.conf'.format(resolv_new)
        echo_result = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd=echo_cmd
        )
        assert_equal(0, echo_result['exit_code'],
                     'Executing "{0}" on the admin node has failed with: {1}'
                     .format(echo_cmd, echo_result['stderr']))
        return resolv_conf['stdout']

    @staticmethod
    @logwrap
    def execute_remote_cmd(remote, cmd, exit_code=0):
        result = remote.execute(cmd)
        assert_equal(result['exit_code'], exit_code,
                     'Failed to execute "{0}" on remote host: {1}'.
                     format(cmd, result))
        return result['stdout']

    @logwrap
    def describe_other_admin_interfaces(self, admin):
        admin_networks = [iface.network.name for iface in admin.interfaces]
        iface_name = None
        for i, network_name in enumerate(admin_networks):
            if 'admin' in network_name and 'admin' != network_name:
                # This will be replaced with actual interface labels
                # form fuel-devops
                iface_name = 'enp0s' + str(i + 3)
                logger.info("Describe Fuel admin node interface {0} for "
                            "network {1}".format(iface_name, network_name))
                self.describe_admin_interface(iface_name, network_name)

        if iface_name:
            return self.ssh_manager.execute(
                ip=self.ssh_manager.admin_ip,
                cmd="cobbler sync")

    @logwrap
    def describe_admin_interface(self, admin_if, network_name):
        admin_net_object = self.d_env.get_network(name=network_name)
        admin_network = admin_net_object.ip.network
        admin_netmask = admin_net_object.ip.netmask
        admin_ip = str(self.d_env.nodes(
        ).admin.get_ip_address_by_network_name(network_name))
        logger.info(('Parameters for admin interface configuration: '
                     'Network - {0}, Netmask - {1}, Interface - {2}, '
                     'IP Address - {3}').format(admin_network,
                                                admin_netmask,
                                                admin_if,
                                                admin_ip))
        add_admin_ip = ('DEVICE={0}\\n'
                        'ONBOOT=yes\\n'
                        'NM_CONTROLLED=no\\n'
                        'USERCTL=no\\n'
                        'PEERDNS=no\\n'
                        'BOOTPROTO=static\\n'
                        'IPADDR={1}\\n'
                        'NETMASK={2}\\n').format(admin_if,
                                                 admin_ip,
                                                 admin_netmask)
        cmd = ('echo -e "{0}" > /etc/sysconfig/network-scripts/ifcfg-{1};'
               'ifup {1}; ip -o -4 a s {1} | grep -w {2}').format(
            add_admin_ip, admin_if, admin_ip)
        logger.debug('Trying to assign {0} IP to the {1} on master node...'.
                     format(admin_ip, admin_if))

        result = self.ssh_manager.execute(
            ip=self.ssh_manager.admin_ip,
            cmd=cmd
        )
        assert_equal(result['exit_code'], 0, ('Failed to assign second admin '
                     'IP address on master node: {0}').format(result))
        logger.debug('Done: {0}'.format(result['stdout']))

        # TODO for ssh manager
        multiple_networks_hacks.configure_second_admin_dhcp(
            self.ssh_manager.admin_ip,
            admin_if
        )
        multiple_networks_hacks.configure_second_admin_firewall(
            self.ssh_manager.admin_ip,
            admin_network,
            admin_netmask,
            admin_if,
            self.get_admin_node_ip()
        )

    @logwrap
    def get_masternode_uuid(self):
        return self.postgres_actions.run_query(
            db='nailgun',
            query="select master_node_uid from master_node_settings limit 1;")
