from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
name: mrjk.ansible.include
plugin_type: inventory
extends_documentation_fragment:
    - constructed
short_description: Include inventory source
description: |
    This inventory module allows to include other inventories by path. It's a somehow
    a possible alternative to symlinks inventories.
     
    Known issues:
    - Does not support collection (yet)
    - Does not allow templating (yet)
author:
    - mrjk
version_added: "2.10"
options:
  plugin:
    description: token that ensures this is a source file for the 'generator' plugin.
    required: True
    choices: ['mrjk.ansible.include', 'include']
  inventory_plugins:
    description: List of acceptable plugins for inventory. Default is `enable_plugins`.
    type: list
    default: []
  files:
    description: Files to include. Non absolute files depends on $PWD.
    type: list
    default: []
'''

EXAMPLES = r'''
# Config examples
plugin: mrjk.ansible.include

inventory_plugins:
  - yaml

files:
  - /home/user/prj/my_project/inventory/default/20_inventories.yml
  - /home/user/prj/my_project/inventory/default/40_profiles.yml
  - /home/user/prj/my_project/inventory/my_org1/10_playbooks.yml
  - inventory/my_product/60_libvirt-wks1.yml
  - inventory/my_product/80_hosts.yml

'''

from ansible.plugins.inventory import BaseInventoryPlugin, Constructable
from ansible.errors import AnsibleError, AnsibleParserError
from ansible.utils.display import Display
from ansible.plugins.loader import inventory_loader


import os

from pprint import pprint
from lxml import etree
import re
display = Display()



from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible import constants as C


class InventoryModule(BaseInventoryPlugin): #, Constructable):
    NAME = 'mrjk.ansible.include'

    def verify_file(self, path):

        valid = False
        if super(InventoryModule, self).verify_file(path):
            file_name, ext = os.path.splitext(path)

            if not ext or ext in ['.config'] + C.YAML_FILENAME_EXTENSIONS:
                valid = True

        return valid

    def parse(self, inventory, loader, path, cache=True):
        super(InventoryModule, self).parse(
            inventory,
            loader,
            path,
            cache=cache
        )

        config_data = self._read_config_data(path)
        self._consume_options(config_data)

        # Add top group to inventory
        #if self.get_option('top_group'):
        #self.inventory.add_group('included')

        # Remove duplicates and keep order
        inventory_plugins = []
        inventory_plugins_raw = self.get_option('inventory_plugins') + list(C.INVENTORY_ENABLED)
        [ inventory_plugins.append(x) for x in inventory_plugins_raw if x not in inventory_plugins]

        # Loop over paths
        paths = self.get_option('files') or []
        for path in paths:

            if not isinstance(path, str):
                display.vvv (f"Include path '{path}' is not a valid string")
                continue
            config_data = loader.load_from_file(path, cache=False)

            # Fetch plugin name from config
            plugin_name = config_data.get('plugin', None)
            if plugin_name:
                plugin_names = [plugin_name]
            else:
                plugin_names = inventory_plugins

            # Test all possible plugins
            display.vvvv (f"Include '{path}': check plugins against: '{plugin_names}'")
            plugin_found = False
            for name in plugin_names:

                # Fetch plugin by name
                plugin = inventory_loader.get(name)
                try:
                    plugin.parse(inventory, loader, path, cache=cache)
                    display.vvv (f"Include '{path}': '{name}' is valid")
                except Exception:
                    display.vvvv (f"Include '{path}': '{name}' is not valid")
                    # Loop again to try another plugin
                    continue

                # Update plugin cache if possible
                try:
                    plugin.update_cache_if_changed()
                except AttributeError:
                    pass

                plugin_found = True
                break

            # Fail of no plugin found
            if not plugin_found:
                display.vvv (f"Include '{path}': Failed to find any valid plugins")
                #raise AnsibleParserError("Could not find valid plugin for file: {path}")






#####        ## Add top role group
#####        #role_group = self.get_option('role_group')
#####        #if isinstance(role_group, str) and role_group != '':
#####        #    role_top_group_name = f"{role_group}s"
#####        #    self.inventory.add_group(f"{role_top_group_name}")
#####        #else:
#####        #    role_group = None
#####
#####        # Reduce source list
#####        flist = self.get_option('files')
#####        print ("PATH:", path)
#####
#####        #self.include(flist)
#####        self.test_inject(flist)
#####
#####    def test_inject(self, flist):
#####        pprint (self.inventory)
#####        pprint (dir(self.inventory))
#####        print ("NEW SRC LIST:", flist)
#####        print ("PROCEEDED SOURCES", self.inventory.processed_sources)
#####        print ("CURRENT SOURCES", self.inventory.current_source)
#####        self.inventory.parse_sources()
#####        print ("OK")
#####        for src in flist:
#####            print ("Parsing source: ", src)
#####            self.inventory.parse_source(src)
#####            print ("Source is parsed")
#####
#####        #return
#####        #inv = InventoryManager(loader=loader, sources=flist)
#####        #pprint (dir(inv))
#####        #pprint ( inv.get_groups_dict() )
#####        #variable_manager = VariableManager(loader=loader, inventory=inventory, version_info=CLI.version_info(gitinfo=False))
#####
#####
#####    def include(self, flist):
#####
#####        print ("=========")
#####        #pprint (self.inventory)
#####        #pprint (dir(self.inventory))
#####        #pprint (self.inventory.serialize())
#####        #print (self.inventory.current_source)
#####        print ("=========")
#####
#####        print ("PARSING: %s" % flist)
#####        inv = InventoryManager(loader=self.loader, sources=flist)
#####        #pprint (self.loader)
#####        pprint (inv)
#####        pprint (dir(inv))
#####        pprint (inv._inventory)
#####        pprint (self.inventory)
#####        pprint (dir(self.inventory))
#####        print ("1. VS")
#####        pprint (inv._inventory.serialize())
#####        print ("2. VS")
#####        pprint (self.inventory.serialize())
#####        print ("3. VS")
#####        return
#####        pprint (dir(inv))
#####        pprint ( inv.serialize() )
#####        #self.inventory = inv
#####        pprint (inv)
#####        pprint (self.inventory)
#####        print ("=========")
#####
#####
#            # Replace invalid characters in hostname
#            if self.get_option('strict'):
#                inventory_hostname_alias = 'virt_uuid_' + \
#                    inventory_hostname_alias.replace('-', '_')
#
#            # Add host to groups
#            self.inventory.add_host(inventory_hostname)
#            if self.get_option('top_group'):
#                if self.get_option('sub_groups'):
#                    self.inventory.add_group(subgroup)
#                    self.inventory.add_child(subgroup, inventory_hostname)
#                    self.inventory.add_child('civirt', subgroup)
#                else:
#                    self.inventory.add_child('civirt', inventory_hostname)
#
#                if isinstance(role_group, str) and role_group != '':
#                    role = re.search('^(?P<role>[^\.]+)[0-9]\..*$',
#                            inventory_hostname, re.IGNORECASE)
#                    if role:
#                        role_name = role.group('role').replace('-', '_')
#                        role_group_name = f"{role_group}_{role_name}"
#
#                        self.inventory.add_group(role_group_name)
#                        self.inventory.add_child(role_group_name, inventory_hostname)
#                        self.inventory.add_child(role_top_group_name, role_group_name)
#
#                        self.inventory.set_variable(
#                            inventory_hostname,
#                            'host_role',
#                            role_name
#                        )
#
#            # Assign connection variables
#            if connection_plugin is not None:
#                self.inventory.set_variable(
#                    inventory_hostname,
#                    'ansible_libvirt_uri',
#                    uri
#                )
#                self.inventory.set_variable(
#                    inventory_hostname,
#                    'ansible_connection',
#                    connection_plugin
#                )
#
#            # Assign extra variables
#            if connection_plugin is None:
#                for k, v in civirt_meta.items():
#                    if k.startswith('civirt_'):
#                        self.inventory.set_variable( inventory_hostname, k, v)
#
#            # Get variables for compose
#            variables = self.inventory.hosts[inventory_hostname].get_vars()
#
#            # Set composed variables
#            self._set_composite_vars(
#                self.get_option('compose'),
#                variables,
#                inventory_hostname,
#                self.get_option('strict'),
#            )
#
#            # Add host to composed groups
#            self._add_host_to_composed_groups(
#                self.get_option('groups'),
#                variables,
#                inventory_hostname,
#                self.get_option('strict'),
#            )
#
#            # Add host to keyed groups
#            self._add_host_to_keyed_groups(
#                self.get_option('keyed_groups'),
#                variables,
#                inventory_hostname,
#                self.get_option('strict'),
#            )
