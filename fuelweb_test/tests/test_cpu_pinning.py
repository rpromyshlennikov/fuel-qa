#    Copyright 2016 Mirantis, Inc.
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

from proboscis import asserts
from proboscis import test

from fuelweb_test.helpers.decorators import log_snapshot_after_test
from fuelweb_test.helpers import utils
from fuelweb_test import logger
from fuelweb_test import settings
from fuelweb_test.tests.base_test_case import SetupEnvironment
from fuelweb_test.tests.base_test_case import TestBasic


@test(groups=["numa_cpu_pinning"])
class NumaCpuPinning(TestBasic):
    """NumaCpuPinning."""

    @test(depends_on=[SetupEnvironment.prepare_slaves_5],
          groups=["numa_cpu_pinning",
                  "basic_env_for_numa_cpu_pinning"])
    @log_snapshot_after_test
    def basic_env_for_numa_cpu_pinning(self):
        """Basic environment for NUMA CPU pinning

        Scenario:
            1. Create cluster
            2. Add 2 nodes with compute role
            3. Add 3 nodes with controller role
            4. Verify that quantity of NUMA is equal on node and in Fuel

        Snapshot: basic_env_for_numa_cpu_pinning
        """
        snapshot_name = 'basic_env_for_numa_cpu_pinning'
        self.check_run(snapshot_name)
        self.env.revert_snapshot("ready_with_5_slaves")

        self.show_step(1, initialize=True)
        cluster_id = self.fuel_web.create_cluster(
            name=self.__class__.__name__,
            mode=settings.DEPLOYMENT_MODE,
            settings={
                "net_provider": 'neutron',
                "net_segment_type": settings.NEUTRON_SEGMENT_TYPE,
                "KVM_USE": True
            }
        )
        self.show_step(2)
        self.show_step(3)

        self.fuel_web.update_nodes(
            cluster_id,
            {
                'slave-01': ['compute'],
                'slave-02': ['compute'],
                'slave-03': ['controller'],
                'slave-04': ['controller'],
                'slave-05': ['controller']
            })

        self.show_step(4)

        for node in ('slave-01', 'slave-02'):
            target_node = self.fuel_web.get_nailgun_node_by_name(node)
            numas_from_fuel = len(
                target_node['meta']['numa_topology']['numa_nodes'])
            numas_on_remote = utils.get_quantity_of_numa(target_node['ip'])
            if not numas_on_remote:
                # Fuel handle topology without NUMA as 1 NUMA node
                asserts.assert_equal(numas_from_fuel, 1,
                                     "No NUMA nodes on {0} "
                                     "while Fuel shows it "
                                     "has {1}".format(
                                         target_node['ip'], numas_from_fuel))
                raise AssertionError("No NUMA nodes on {0}".format(
                                     target_node['ip']))
            else:
                asserts.assert_equal(numas_on_remote, numas_from_fuel,
                                     "{0} NUMA nodes on {1} "
                                     "while Fuel shows it "
                                     "has {2}".format(
                                         numas_on_remote, target_node['ip'],
                                         numas_from_fuel))
                logger.info("There is {0} NUMA nodes on node {1}".format(
                    numas_on_remote, target_node['ip']))
        self.env.make_snapshot(snapshot_name, is_make=True)
