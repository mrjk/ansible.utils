#my_csv_plugin.py

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
    name: exclude
    plugin_type: inventory
    short_description: Filter out hosts or groups
    description: >
        Remove from the inventory the hosts you don't want to see. It replace with some advantages
        the INVENTORY_IGNORE_PATTERNS option of ansible configuration, except it does not support (yet)
        regex.
    author:
        - mrjk
    options:
      plugin:
          description: Name of the plugin
          required: true
          choices: ['exclude']
      exclude_hosts:
        description: Exclude list of host patterns
        required: false
        default: []
      exclude_groups:
        description: Exclude list of group patterns
        required: false
        default: []
'''
EXAMPLES = '''
plugin: exclude

exclude_hosts:
  - server_inventory_hostname
  - server.domain.net

exclude_groups:
  - beta
  - devel

'''


from ansible.plugins.inventory import BaseInventoryPlugin
from ansible.errors import AnsibleError, AnsibleParserError

from pprint import pprint

class InventoryModule(BaseInventoryPlugin):
    NAME = 'exclude'

    def verify_file(self, path):
        return True
    
    def parse(self, inventory, loader, path, cache):
        '''Return dynamic inventory from source '''

        super(InventoryModule, self).parse(inventory, loader, path, cache)
        self._read_config_data(path)

        # Fetch current inventory
        group_dict = dict(self.inventory.get_groups_dict())
        host_dict = dict(self.inventory.hosts)

        # Exclude hosts and groups list
        exclude_groups = self.get_option('exclude_groups')
        exclude_hosts = self.get_option('exclude_hosts')
        exclude_hosts_group = []

        # Exclude host groups
        for group_name in exclude_groups:
            if group_name in group_dict:
                host_list = group_dict.get(group_name, [])
                self.display.v('Excluded hosts from group %s: %s' % (group_name, host_list))
                exclude_hosts_group.extend(host_list)

        # Exclude hosts
        exclude_hosts.extend(exclude_hosts_group)
        for host in exclude_hosts:
            if host in host_dict:
                h = self.inventory.get_host(host)
                self.display.v('Exclude host: %s' % (h))
                self.inventory.remove_host(h)

        # Exclude groups
        for group_name in exclude_groups:
            if group_name in group_dict:

                exclude_hosts_group.extend(group_dict.get(group_name, []))
                self.display.v('Exclude group: %s' % (group_name))
                self.inventory.remove_group(group_name)

