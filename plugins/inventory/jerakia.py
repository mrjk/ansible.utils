# -*- coding: utf-8 -*-
# Copyright (c) 2020 mrjk
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

# pylint: disable=raise-missing-from
# pylint: disable=super-with-arguments

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
    name: jerakia
    plugin_type: inventory
    short_description: Jerakia host variable inventory source
    requirements:
        - requests >= 1.1
    description:
        - Get host variables from Jerakia (http://jerakia.io/)
        - This plugin get all hosts from inventory and add lookep up keys
        - It's important to make this inventory source loaded after all other hosts has been declared. To force whit behavior, you can name your inventory file by `zzz_` to be sure it will be the last one to be parsed
    extends_documentation_fragment:
        - inventory_cache
        - constructed
    options:
      plugin:
        description: token that ensures this is a source file for the C(jerakia) plugin.
        required: True
        choices: ['jerakia']

      token:
        description:
          - The Jerakia token to use to authenticate against Jerakia server.
        default: ''
        env:
            - name: ANSIBLE_JERAKIA_TOKEN
      host:
        description:
          - Hostname of the Jerakia Server.
        default: '127.0.0.1'
        env:
            - name: ANSIBLE_JERAKIA_HOST
      port:
        description:
          - Jerakia port to connect to.
        default: '9843'
        env:
            - name: ANSIBLE_JERAKIA_PORT
      protocol:
        description:
          - The URL protocol to use.
        default: 'http'
        choices: ['http', 'https']
        env:
            - name: ANSIBLE_JERAKIA_PROTOCOL
      version:
        description:
          - Jerakia API version to use.
        default: 1
        choices: [1]
        env:
            - name: ANSIBLE_JERAKIA_VERSION
      cache:
        description:
          - Enable Jerakia inventory cache.
        default: false
        type: boolean
        env:
            - name: ANSIBLE_JERAKIA_CACHE

      keys:
        description:
          - A list of keys to lookup
        default: {}
      scope:
        description:
          - A hash containing the scope to use for the request, the values will be resolved as Ansible facts.
          - Use a dot notation to dig deeper into nested hash facts.
        default: {}
      policy:
        description:
          - Jerakia policy to use for the lookups.
        default: 'default'

      validate_certs:
        description:
          - Whether or not to verify the TLS certificates of the Jerakia server.
        type: boolean
        default: False
        env:
            - name: ANSIBLE_JERAKIA_VALIDATE_CERTS
      use_vars_plugins:
          description:
              - Normally, for performance reasons, vars plugins get executed after the inventory sources complete the base inventory,
                this option allows for getting vars related to hosts/groups from those plugins.
              - The host_group_vars (enabled by default) 'vars plugin' is the one responsible for reading host_vars/ and group_vars/ directories.
              - This will execute all vars plugins, even those that are not supposed to execute at the 'inventory' stage.
                See vars plugins docs for details on 'stage'.
          required: false
          default: false
          type: boolean
          version_added: '2.11'

'''

EXAMPLES = '''
# zzz_dev.jerakia.yml
plugin: jerakia
host: 127.0.0.1
token: xxx:yyy
scope:
  fqdn: inventory_hostname


# zzz_prod.jerakia.yml
plugin: jerakia
host: jerakia.domain.tld
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
from ansible import constants as C
from distutils.version import LooseVersion
from ansible.errors import AnsibleError
from ansible.plugins.inventory import BaseInventoryPlugin, Cacheable, Constructable


# 3rd party imports
try:
    import requests
    if LooseVersion(requests.__version__) < LooseVersion('1.1.0'):
        raise ImportError
    from requests.auth import HTTPBasicAuth
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class Jerakia(object):
    def __init__(self, base):
        self.base = base
        self.config = self.get_config()

    def config_defaults(self):
        return {
            'protocol': 'http',
            'host': '127.0.0.1',
            'port': '9843',
            'version': '1',
            'policy': 'default'
        }

    def override_defaults(self):
        return {
            'protocol': os.environ.get('ANSIBLE_JERAKIA_PROTOCOL', None),
            'host':  os.environ.get('ANSIBLE_JERAKIA_HOST', None),
            'port':  os.environ.get('ANSIBLE_JERAKIA_PORT', None),
            'token':  os.environ.get('ANSIBLE_JERAKIA_TOKEN', None),
            'version':  os.environ.get('ANSIBLE_JERAKIA_VERSION', None),
            'policy':  os.environ.get('ANSIBLE_JERAKIA_POLICY', None)
        }

    def get_config(self, configfile=os.environ.get('ANSIBLE_JERAKIA_CONFIG', 'jerakia.yaml')):
        defaults = self.config_defaults()

        if os.path.isfile(configfile):
            data = open(configfile, "r")
            defined_config = yaml.safe_load(data)
            combined_config = defaults.copy()
            combined_config.update(defined_config)
            for k, v in self.override_defaults().items():
                if v is not None:
                    combined_config[k] = v
            return combined_config
        else:
            raise AnsibleError("Unable to find configuration file %s" % configfile)

    def lookup_endpoint_url(self, key=''):
        proto = self.config["protocol"]
        host = self.config['host']
        port = self.config['port']
        version = self.config['version']
        url = "%(proto)s://%(host)s:%(port)s/v%(version)s/lookup/%(key)s" % locals()
        return url

    def dot_to_dictval(self, dic, key):
        key_arr = key.split('.')
        this_key = key_arr.pop(0)

        if this_key not in dic:
            raise AnsibleError("Cannot find key %s " % key)

        if len(key_arr) == 0:
            return dic[this_key]

        return self.dot_to_dictval(dic[this_key], '.'.join(key_arr))

    def scope(self, variables):
        scope_data = {}
        scope_conf = self.config['scope']
        if not self.config['scope']:
            return {}
        for key, val in scope_conf.items():
            metadata_entry = "metadata_%(key)s" % locals()
            scope_value = self.dot_to_dictval(variables, val)
            scope_data[metadata_entry] = scope_value
        return scope_data

    def headers(self):
        token = self.config.get('token', None)
        if not token:
            raise AnsibleError('No token configured for Jerakia')

        return {
            'X-Authentication': token,
            'content_type': 'application/json'
        }

    def lookup(self, key, namespace, policy='default', variables=None, kwargs=None):
        
        endpoint_url = self.lookup_endpoint_url(key=key)
        namespace_str = '/'.join(namespace)
        #scope = self.scope(variables)
        scope = variables
        kwargs = kwargs or {}
        options = {
            'namespace': namespace_str,
            'policy': policy,
        }

        params = scope.copy()
        params.update(options)
        params.update(kwargs)
        headers = self.headers()

        response = requests.get(endpoint_url, params=params, headers=headers)
        if response.status_code == requests.codes.ok:
            return json.loads(response.text)
        else:
            raise AnsibleError(f"Bad HTTP response, got: {response.status_code}{response.reason}: {response.status_code} on {response.url}: {response.text}")


class InventoryModule(BaseInventoryPlugin, Cacheable, Constructable):
    NAME = 'jerakia'

    def verify_file(self, path):
        valid = False
        if super(InventoryModule, self).verify_file(path):
            if path.endswith(('jerakia.yaml', 'jerakia.yml')):
                valid = True
        return valid

    def lookup_host_data(self, host):

        # Build the scope
        scope = {}
        host_vars = host.get_vars()
        for k, v in self.scope.items():
            scope[f"metadata_{k}"] = host_vars.get(v, None)
        self.display.vvv(f"Jerakia scope for {host.name}: {scope}")

        # Query each keys
        new_vars = {}
        for var, term in self.keys.items() :
            # Build query
            lookuppath = term.split('/')
            key = lookuppath.pop()
            namespace = lookuppath
            if not namespace:
                raise AnsibleError("No namespace given for lookup of key %s" % key)

            # Run the query
            response = self.jerakia.lookup(key=key, namespace=namespace, variables=scope, kwargs={})
            new_vars[var] = response['payload']

        return new_vars

    def parse(self, inventory, loader, path, cache):
        '''Return dynamic inventory from source '''

        super(InventoryModule, self).parse(inventory, loader, path, cache)
        self._read_config_data(path)

        # Read configuration
        self.keys = self.get_option('keys')
        self.scope = self.get_option('scope')
        self.strict = self.get_option('strict')

        self.cache_enabled = os.environ.get(
                'ANSIBLE_JERAKIA_CACHE',
                str(self.get_option('cache'))
                ).lower() in ('true', '1', 't')

        # Determine cache behavior
        attempt_to_read_cache = self.cache_enabled and cache

        # Fetch all hosts and request jerakia data
        self.jerakia = Jerakia(self)
        for host_name in inventory.hosts:
            
            # Select an host
            host = self.inventory.get_host(host_name)
            cache_key = self.get_cache_key(f"{path}/{host_name}")
            cache_needs_update = self.cache_enabled and not cache

            self.display.v("Checking Cache")
            # Check if data is available in cache
            if attempt_to_read_cache:
                try:
                    # There is something in the cache
                    results = self._cache[cache_key]
                    self.display.v(f"Cached data found for {host_name}: {results}")
                except KeyError:
                    # There is nothing in cache, so we want to update it
                    self.display.v(f"No cache found for {host_name}")
                    cache_needs_update = True


            if not attempt_to_read_cache or cache_needs_update:
                # We don't have cache, or we don't want to use cache, so we do the query
                results = self.lookup_host_data(host)
                self.display.vv(f"Jerakia found variables for {host.name}: {results}")

            if cache_needs_update:
                # Update cache if needed
                self._cache[cache_key] = results

            # Add variables to the host
            for var, val in results.items():
                host.set_variable(var, val)

            # Call constructed inventory plugin methods
            hostvars = self.inventory.get_host(host_name).get_vars()
            self._set_composite_vars(self.get_option('compose'), hostvars, host_name, self.strict)
            self._add_host_to_composed_groups(self.get_option('groups'), hostvars, host_name, self.strict)
            self._add_host_to_keyed_groups(self.get_option('keyed_groups'), hostvars, host_name, self.strict)


