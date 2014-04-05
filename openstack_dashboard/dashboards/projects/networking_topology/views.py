# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2013 NTT MCL Inc.
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

import json

from django.conf import settings  # noqa
from django.core.urlresolvers import reverse  # noqa
from django.core.urlresolvers import reverse_lazy  # noqa
from django.http import HttpResponse  # noqa
from django.views.generic import TemplateView  # noqa
from django.views.generic import View  # noqa

from openstack_dashboard import api

from .instances \
    import tables as instances_tables
from .ports \
    import tables as ports_tables
from .routers \
    import tables as routers_tables

from openstack_dashboard.dashboards.project.instances import\
    views as i_views
from openstack_dashboard.dashboards.project.instances.workflows import\
    create_instance as i_workflows
from contrail_openstack_dashboard.openstack_dashboard.dashboards.projects.networking import\
    views as n_views


class NTCreateNetwork (n_views.CreateNetworkView):
    success_url = "horizon:project:networking_topology:index"
    def get_success_url(self):
        return reverse("horizon:project:networking_topology:index")

    def get_failure_url(self):
        return reverse("horizon:project:networking_topology:index")


class NTLaunchInstance (i_workflows.LaunchInstance):
    success_url = "horizon:project:networking_topology:index"


class NTLaunchInstanceView (i_views.LaunchInstanceView):
    workflow_class = NTLaunchInstance


class InstanceView (i_views.IndexView):
    table_class = instances_tables.InstancesTable
    template_name = 'project/networking_topology/iframe.html'


class NetworkTopologyView (TemplateView):
    template_name = 'project/networking_topology/index.html'


class JSONView(View):
    def add_resource_url(self, view, resources):
        tenant_id = self.request.user.tenant_id
        for resource in resources:
            if (resource.get('tenant_id')
                    and tenant_id != resource.get('tenant_id')):
                continue
            resource['url'] = reverse(view, None, [str(resource['id'])])

    def _check_router_external_port(self, ports, router_id, network_id):
        for port in ports:
            if (port['network_id'] == network_id
                    and port['device_id'] == router_id):
                return True
        return False

    def get(self, request, *args, **kwargs):
        data = {}
        # Get nova data
        try:
            servers, more = api.nova.server_list(request)
        except Exception:
            servers = []
        console_type = getattr(settings, 'CONSOLE_TYPE', 'AUTO')
        if console_type == 'SPICE':
            console = 'spice'
        else:
            console = 'vnc'
        data['servers'] = [{'name': server.name,
                            'status': server.status,
                            'console': console,
                            'task': getattr(server, 'OS-EXT-STS:task_state'),
                            'id': server.id} for server in servers]
        self.add_resource_url('horizon:project:instances:detail',
                              data['servers'])

        # Get neutron data
        # if we didn't specify tenant_id, all networks shown as admin user.
        # so it is need to specify the networks. However there is no need to
        # specify tenant_id for subnet. The subnet which belongs to the public
        # network is needed to draw subnet information on public network.
        try:
            neutron_public_networks = api.neutron.network_list(
                request,
                **{'router:external': True})
            neutron_networks = api.neutron.network_list_for_tenant(
                request,
                request.user.tenant_id)
            neutron_ports = api.neutron.port_list(request,
                                                  tenant_id=request.user.tenant_id)
            neutron_routers = api.neutron.router_list(
                request,
                tenant_id=request.user.tenant_id)
        except Exception:
            neutron_public_networks = []
            neutron_networks = []
            neutron_ports = []
            neutron_routers = []

        networks = [{'name': network.name,
                    'id': network.id,
                    'subnets': [{'cidr': subnet.cidr}
                                for subnet in network.subnets],
                    'router:external': network['router:external']}
                    for network in neutron_networks]
        # Add public networks to the networks list
        for publicnet in neutron_public_networks:
            found = False
            for network in networks:
                if publicnet.id == network['id']:
                    found = True
            if not found:
                try:
                    subnets = [{'cidr': subnet.cidr}
                               for subnet in publicnet.subnets]
                except Exception:
                    subnets = []
                networks.append({
                    'name': publicnet.name,
                    'id': publicnet.id,
                    'subnets': subnets,
                    'router:external': public['router:external']})
        data['networks'] = sorted(networks,
                                  key=lambda x: x.get('router:external'),
                                  reverse=True)

        data['ports'] = [{'id': port.id,
                          'network_id': port.network_id,
                          'device_id': port.device_id,
                          'fixed_ips': port.fixed_ips,
                          'device_owner': port.device_owner,
                          'status': port.status
                          }
                         for port in neutron_ports]

        data['routers'] = [{
            'id': router.id,
            'name': router.name,
            'status': router.status,
            'external_gateway_info': router.external_gateway_info}
            for router in neutron_routers]

        # user can't see port on external network. so we are
        # adding fake port based on router information
        for router in data['routers']:
            external_gateway_info = router.get('external_gateway_info')
            if not external_gateway_info:
                continue
            external_network = external_gateway_info.get(
                'network_id')
            if not external_network:
                continue
            if self._check_router_external_port(data['ports'],
                                                router['id'],
                                                external_network):
                continue
            fake_port = {'id': 'fake%s' % external_network,
                         'network_id': external_network,
                         'device_id': router['id'],
                         'fixed_ips': []}
            data['ports'].append(fake_port)

        json_string = json.dumps(data, ensure_ascii=False)
        return HttpResponse(json_string, mimetype='text/json')