# -*- coding: utf-8 -*-
# Copyright (c) 2020 mrjk
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# pylint: disable=raise-missing-from
# pylint: disable=super-with-arguments

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
    name: terraform
    plugin_type: inventory
    short_description: Jerakia host variable inventory source
    requirements:
        - requests >= 1.1
    description:
        - Get host variables from Jerakia (http://terraform.io/)
        - This plugin get all hosts from inventory and add lookep up keys
        - It's important to make this inventory source loaded after all other hosts has been declared. To force whit behavior, you can name your inventory file by `zzz_` to be sure it will be the last one to be parsed
    extends_documentation_fragment:
        - inventory_cache
        - constructed
    options:
      plugin:
        description: token that ensures this is a source file for the C(terraform) plugin.
        required: True
        choices: ['terraform','mrjk.utils.terraform']

      cache:
        description:
          - Enable Jerakia inventory cache.
        default: false
        type: boolean
        env:
            - name: ANSIBLE_JERAKIA_CACHE
      strict:
          description: Strict hostnames
          type: bool
          default: true

      inventory_group:
        description:
          - A name of a top group where to put all instances under
        default: ''
      inventory_sub_groups:
        description:
          - A name of a top group where to put all instances under
        default: True
        type: boolean

      backends:
        description:
          - A hash containing all available backends
        default: {}
      stacks:
        description:
          - A list containing stacks to imports
        default: []

'''

EXAMPLES = '''
# zzz_dev.terraform.yml
plugin: terraform
host: 127.0.0.1
token: xxx:yyy
scope:
  fqdn: inventory_hostname


# zzz_prod.terraform.yml
plugin: terraform
host: terraform.domain.tld
protocol: https
token: xxx:yyy
scope:
  fqdn: inventory_hostname
  hostgroup: foreman_hostgroup_title
  organization: foreman_organization_name
  location: foreman_location_name
  environment: foreman_environment_name
'''
import json
import yaml
import os
import base64
import re
from pprint import pprint

from ansible import constants as C
from distutils.version import LooseVersion
from ansible.errors import AnsibleError
from ansible.plugins.inventory import BaseInventoryPlugin, Cacheable, Constructable
from ansible.utils.display import Display


# 3rd party imports
try:
    import requests
    if LooseVersion(requests.__version__) < LooseVersion('1.1.0'):
        raise ImportError
    from requests.auth import HTTPBasicAuth
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False



#
# Init
# ===============================================

display = Display()

#def flatten(t):
#    return [item for sublist in t for item in sublist]

def flatten(list_of_lists):
    if len(list_of_lists) == 0:
        return list_of_lists
    if isinstance(list_of_lists[0], list):
        return flatten(list_of_lists[0]) + flatten(list_of_lists[1:])
    return list_of_lists[:1] + flatten(list_of_lists[1:])

#
# Ansible Terraform Inventory Plugin
# ===============================================






class TerraformPlugin():

    default_stack_conf = {
            'name': None,
            'backend': 'local',
            }
    default_backend_conf = {
            'name': None,
            'backend': 'local',
            }

    def get_hosts(self, stacks_conf, backends_conf):
        out = self.expand_stacks( stacks_conf, backends_conf)
        assert isinstance(out, dict)
        return out

    def expand_stacks(self, stacks_conf, backends_conf):

        stacks = self.parse_config(stacks_conf, backends_conf)
        ret = {}
        for stack in stacks:
            name = stack.config.get('name', '.*')
            display.vvv("Parsing Stack: ", stack)
            resources = stack.expand_conf()
            assert isinstance(resources, dict)

            for host_name, host_def in resources.items():
                if host_name in ret:
                    print ("Duplicated host found", host_name)
                else:
                    ret[host_name] = host_def
        return ret




    def parse_config(self, stacks_conf, backends_conf):
        """Parse module configuration"""
        backends = self.parse_backends(backends_conf)
        stacks = self.parse_stacks(stacks_conf, backends)
        return stacks

    def parse_backends(self, backends_conf):
        """Return a dict of terraform backend objects"""
        assert isinstance(backends_conf, dict)
        
        ret = {}
        for name, backend_def in backends_conf.items():
            new_def = self.default_backend_conf.copy()
            new_def.update(backend_def)

            kind = backend_def.get('type', 'local')
            if kind == 'consul':
                ret[name] = TerraformConsul(name, new_def)
                #ret[name] = 'CONSUL'
            elif kind == 'local':
                #ret[name] = TerraformLocal(name, new_def)
                ret[name] = 'LOCAL'
            else:
                raise AnsibleError(
                        f"Unsupported backend type '{kind} for backend {name}'")
        return ret

    def parse_stacks(self, stacks_conf, backends):
        """Return a list of terraform stack objects"""
        assert isinstance(stacks_conf, list)
        assert isinstance(backends, dict)
        
        ret = []
        for idx, stack_def in enumerate(stacks_conf):
            new_def = self.default_stack_conf.copy()
            new_def.update(stack_def)

            new_def['index'] = idx
            stack = TerraformStack(new_def, backends)
            ret.append(stack)
        return ret


#
# Resource drivers
# ===============================================

class Driver():
    name = ''
    types = []

    default_host_def = {
            "inventory_hostname": None,
            "inventory_hostname_short": None,
            "group_names": None,
            "hostvars": None,

            "ansible_become_user": None,
            "ansible_connection": None,
            "ansible_host": None,
            "ansible_python_interpreter": None,
            "ansible_user": None,
        }

    def filter_provider_type(self, instances, types):
        """Filter out resources that not in types list"""
        assert isinstance(types, list)
        return [ i for i in instances if i.get('type') in types ]


    def __init__(self, resources):
        self.all_data = resources
        res = self.filter_provider_type(resources, self.types)
        display.vv(f"Reduced from {len(resources)} to {len(res)} resources for driver '{self.name}'")
        self.data = res


    def get_hosts(self):

        instances = []
        for inst in self.data:
            instances.extend(inst.get('instances', []))

        display.vv(f"Number of hosts to deal with: {len(instances)}")
        ret = self.loop_over_hosts(instances)

        return ret


class AnsibleHost(Driver):
    """Support for nbering/ansible ansible_host resources"""

    name = 'nbering/ansible'
    types = ['ansible_host']

    def loop_over_hosts(self, hosts):
        """Loop over ansible_host resources"""
        assert isinstance(hosts, list)

        ret = {}
        for host_res in hosts:
            attr = host_res.get('attributes', None)
            if not attr:
                continue

            inventory_hostname = attr.get('inventory_hostname')
            if inventory_hostname in ret:
                display.v(f"Duplicate host found for: {inventory_hostname}")
                continue
            ret[inventory_hostname] = attr

        return ret

class LibvirtDomain(Driver):
    """Work in progress"""

    name = 'dmarcvicard/libvirt'
    types = ['libvirt_domain']

    def loop_over_hosts(self, hosts):
        assert isinstance(hosts, list)

        ret = {}
        for host_res in hosts:
            attr = host_res.get('attributes', None)
            if not attr:
                continue

            pprint (attr)
            print ("===============")
            pprint (self.all_data)
            raise Exception("Work in progress, not implemented yet !")

            # Extract host data
            inventory_hostname = attr.get('name')
            inventory_hostname_short = inventory_hostname.split('.')[0]

            # Other infos
            network_interfaces = attr.get('network_interface')
            running = attr.get('running')
            machine = attr.get('machine')
            _id = attr.get('id')
            emulator = attr.get('emulator')
            description = attr.get('description')
            cpu = attr.get('cpu')
            cloudinit = attr.get('cloudinit')
            autostart = attr.get('autostart')
            arch = attr.get('arch')
            metadata = attr.get('metadata')
            qemu_agent = attr.get('qemu_agent')
            #id = attr.get('id')


            # Build host config
            host = self.default_host_def.copy()
            host["inventory_hostname"] = inventory_hostname
            host["inventory_hostname_short"] = inventory_hostname_short
            host["group_names"] = None
            host["hostvars"] = None
            host["ansible_become_user"] = None
            host["ansible_connection"] = None
            host["ansible_host"] = None
            host["ansible_python_interpreter"] = None
            host["ansible_user"] = None

            ret[inventory_hostname] = host

        return ret
#   
# Stack
# ===============================================

class TerraformStack():
    """Class that represent a stack element"""

    default_config ={
            'name': None,
            'driver': None,
            'backend': 'local',
            }

    driver_map = {
            'libvirt_domain': LibvirtDomain,
            'ansible_host': AnsibleHost,
            }

    def __init__(self, config, backends):
        self.config = self.get_config(config)
        backend_name = config.get('backend')
        self.backend = backends[backend_name]

    def get_config(self, config):
        conf = {}
        conf.update(self.default_config)
        conf.update(config)
        return conf

    def get_stacks(self):
        backend = self.backend
        return backend.get_stacks()

    def _expand_paths(self):
        """Expand path pattern to list of paths"""
        name = self.config['name']
        r = re.compile(name)

        all_stacks = self.backend.get_stacks()
        ret = list(filter(r.match, all_stacks))
        return ret

    def expand_conf(self):
        paths = self._expand_paths()

        ret = {}
        for path in paths:
            # Call backend lookup with path !
            res = self.backend.get_resources(path)

            backend_type = self.backend.config['driver']
            stack_type = self.config['driver']
            driver_name = stack_type or backend_type or None

            try:
                driver_cls = self.driver_map[driver_name]
            except Exception as err:
                raise Exception(f"Could not find driver '{driver_name}'")

            driver = driver_cls(res)
            hosts = driver.get_hosts()
        
            for host_name, host_def in hosts.items():
                if host_name in ret:
                    print (f"Duplicate host found: {host_name}")
                    continue
                    
                # Inject Stack context vars
                #host_def['vars']['terraform_stack'] = path
                inventory_conf = {}
                inventory_conf['stack'] = path
                inventory_conf['driver'] = driver_name
                host_def['terraform'] = inventory_conf
                host_def['vars'].update({f"terraform_{k}": v for k, v in inventory_conf.items() })

                ret[host_name] = host_def

        return ret

#
# Backends
# ===============================================

class TerraformBackend():
    """Generic class for backends"""

    default_config = {
            'type': None,
            'prefix': None,
            'driver': None,
            }

    def __init__(self, name, base):
        self.name = name
        self.base = base
        self.config = self.get_config()
        self.cache = {}

    def get_config(self, configfile=None):
        if not configfile:
            configfile=os.environ.get('ANSIBLE_TERRAFORM_CONFIG', 'terraform.yml')
            # TODO: Load config file
        #defaults = self.config_defaults()
        conf = {}
        conf.update(self.default_config)
        conf.update(self.base)
        return conf

    def get_stacks(self):
        """Return a list of found state under the form of prefixes"""
        print ("NOT IMPLEMENTED")
        return []

    def get_resources(self, state_prefix):
        """Return a list of state resources"""
        print ("NOT IMPLEMENTED")
        return []

    def remove_prefix(self, lst, prefix):
        assert isinstance(lst, list)

        return [ item.lstrip(prefix) for item in lst ]


# See: https://github.com/nbering/terraform-inventory/blob/master/terraform.py

#
# Backends plugins
# ===============================================

class TerraformConsul(TerraformBackend):
    """Consul backend"""

    default_config = {
            'type': None,
            'prefix': '/terraform/state/',

            'protocol': 'http',
            'host': '127.0.0.1',
            'port': '8600',
            'version': '1',
            'token': None
        }

    def get_url(self, key=''):
        proto = self.config["protocol"]
        host = self.config['host']
        port = self.config['port']
        version = self.config['version']
        url = "%(proto)s://%(host)s:%(port)s/v%(version)s/kv%(key)s" % locals()
        return url

    def get_resources(self, path, kwargs=None):
        """Fetch terrastate config and extract resource field"""
        prefix = self.config['prefix']
        key = f"{prefix}{path}"
        url = self.get_url(key=key)

        # Check internal cache
        if url in self.cache:
            return self.cache[url]

        # Prepare http query
        payload_ = self.kv_get(url)
        if not isinstance(payload_, list):
            raise Exception ("Wrong type")
            #if self.config['nofail']:
            #    return []

        # Loop over all resources ...
        ret = []
        for payload in payload_:
            key_name = payload.get('Key')
            value = payload.get('Value')

            # TOFIX HERE:
            # print (value)
            if not value:
                print ("Missing stack data ...")
                continue
            #try:
            #    value = base64.b64decode(value)
            #except Exception as err:
            #    raise Exception(err)
            value = base64.b64decode(value)


            value = json.loads(value)
            value = value.get('resources')
            self.cache[url] = value

            display.vv(f"Found resources in '{self.name}' backend with key '{key}'")
            return value

        display.vvv(f"No resources found in '{self.name}' backend with key '{key}'")
        return None



    def get_stacks(self, path=None):
        """Get a list of all known state in this backend"""
        prefix = self.config['prefix']
        key = prefix
        if path:
            key = f"{prefix}path"
        url = self.get_url(key=key)

        # Check internal cache
        if url in self.cache:
            return self.cache[url]

        # Prepare http query
        params = {
                'recurse': True,
                'keys': True
                }
        payload = self.kv_get(url, params=params)
        if not isinstance(payload, list):
            raise Exception ("Wrong type")
            #if self.base.get('nofail', False):
            #    return []

        ret = self.remove_prefix(payload, prefix)
        self.cache[url] = ret
        display.v(f"Found {len(ret)} stack(s) in '{self.name}' backend with prefix '{prefix}': {', '.join(ret)}")
        return ret

    def kv_get(self, url, params=None, headers=None ):
        assert isinstance(url, str)
        params = params or {}
        headers = headers or {}

        try:
            display.vv(f"Fetching url: {url} ...")
            if params:
                display.vvv(f"Url params: {params}")
            if headers:
                display.vvv(f"Url headers: {headers}")
            response = requests.get(url, params=params, headers=headers)
        except Exception as e:
            #if self.base.nofail:
            #    return []
            raise AnsibleError(
                    f"Could not fetch url {url}, got error: {e}")

        # Process result
        ret = None
        if response.status_code == requests.codes.ok:
            ret = json.loads(response.text)
        else:
            raise AnsibleError(
                    f"Bad HTTP response, got: {response.status_code}{response.reason}: "
                    f"{response.status_code} on {response.url}: {response.text}")
        return ret

class TerraformLocal(TerraformBackend):
    """Local backend"""

    default_config = {
            'type': None,
            'prefix': '/',

            'directory': 'terraform',
        }


#
# Inventory Module
# ===============================================

class InventoryModule(BaseInventoryPlugin, Cacheable, Constructable):
    NAME = 'terraform'

    def verify_file(self, path):
        valid = False
        if super(InventoryModule, self).verify_file(path):
            if path.endswith(('tfstate.yaml', 'tfstate.yml')):
                valid = True
            if path.endswith(('terraform.yaml', 'terraform.yml')):
                valid = True
        return valid


    def parse(self, inventory, loader, path, cache):
        '''Return dynamic inventory from source '''

        super(InventoryModule, self).parse(inventory, loader, path, cache)
        self._read_config_data(path)

        self.backends_def = self.get_option('backends')
        self.stacks_def = self.get_option('stacks')
        self.strict = self.get_option('strict')
        self.inventory_group = self.get_option('inventory_group')
        self.inventory_sub_groups = self.get_option('inventory_sub_groups')
        plugin = TerraformPlugin()
        terraform_hosts = plugin.get_hosts(self.stacks_def, self.backends_def)

        # Add inventory group
        if self.inventory_group:
            self.inventory.add_group(self.inventory_group)

        for host_name, host_def in terraform_hosts.items():
            # pprint (host_def)

            # Replace invalid characters in hostname
            if self.strict:
                host_name = host_name.replace('_', '-')

            # Add host and vars to inventory
            self.inventory.add_host(host_name)
            for var, val in host_def.get('vars', {}).items():
                self.inventory.set_variable(host_name, var, val)

            # Add to plugin groups
            if self.inventory_group:

                if self.inventory_sub_groups:
                    subgroup = host_def['terraform']['stack']
                    subgroup = subgroup.replace('/', '_')
                    subgroup = subgroup.replace('-', '_')
                    self.inventory.add_group(subgroup)
                    self.inventory.add_child(subgroup, host_name)
                    self.inventory.add_child(self.inventory_group, subgroup)
                else:
                    self.inventory.add_child(self.inventory_group, host_name)
            
            # Add to custom groups
            for group in host_def["groups"]:
                if not group:
                    continue
                self.inventory.add_group(group)
                self.inventory.add_child(group, host_name)

            # Get variables for compose
            variables = self.inventory.hosts[host_name].get_vars()

            # Set composed variables
            self._set_composite_vars(
                self.get_option('compose'),
                variables,
                host_name,
                self.get_option('strict'),
            )

            # Add host to composed groups
            self._add_host_to_composed_groups(
                self.get_option('groups'),
                variables,
                host_name,
                self.get_option('strict'),
            )

            # Add host to keyed groups
            self._add_host_to_keyed_groups(
                self.get_option('keyed_groups'),
                variables,
                host_name,
                self.get_option('strict'),
            )

