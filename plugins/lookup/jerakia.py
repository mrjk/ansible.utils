# Copyright 2021 mrjk
# Copyright 2017 Craig Dunn <craig@craigdunn.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import requests
import yaml

from copy import deepcopy
from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.template import generate_ansible_template_vars, AnsibleEnvironment, USE_JINJA2_NATIVE

try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()

if USE_JINJA2_NATIVE:
    from ansible.utils.native_jinja import NativeJinjaText

DOCUMENTATION = """
  lookup: jerakia
  author: mrjk
  version_added: "3"
  short_description: read key/values from Jerakia
  description:
      - This lookup returns the contents of a Jerakia key
      - This is an improved fork of https://github.com/jerakia/jerakia-ansible-lookup-plugin
      - This fork provides python3 support and more query options
  options:
    _terms:
      description: One or more string terms prefixed by a namespace. Format is `<namespace>/<key>`.
      required: True
    lookup_type:
      description: Lookup type, can be one of `first` or `cascade`
      required: False
    merge:
      description: Merge strategy, can be one of `array`, `deep_hash` or `hash`
      required: False
    enable_jinja:
      description:
          - Enable or not Jinja rendering
      default: True
      version_added: '2.11'
      type: bool
    jinja2_native:
      description:
          - Controls whether to use Jinja2 native types.
          - It is off by default even if global jinja2_native is True.
          - Has no effect if global jinja2_native is False.
          - This offers more flexibility than the template module which does not use Jinja2 native types at all.
          - Mutually exclusive with the convert_data option.
      default: False
      version_added: '2.11'
      type: bool
  notes:
    - Jerakia documentation is available on http://jerakia.io/
    - You can add more parameters as documented in http://jerakia.io/server/api
"""

EXAMPLES = """
- name: Return the value of key
  debug:
    msg: "{{ lookup('jerakia', 'default/key') }}"

- name: Return a list of values
  debug:
    msg: "{{ lookup('jerakia', 'ansible/yum_packages', 'ansible/yum_repos') }}"

- name: Advanced usage
  debug:
    msg: "{{ lookup('jerakia', 'ansible/yum_packages', merge='deep_hash', lookup_type='cascade') }}"

- name: Advanced usage with custom parameters
  debug:
    msg: "{{ lookup('jerakia', 'ansible/yum_packages', policy='ansible') }}"

"""

RETURN = """
  _data:
    description:
      - Value of the key, when only one term is searched
  _list:
    description:
      - List of value of the keys, when more than one term is searched
    type: list

"""


class Jerakia(object):
    def __init__(self, base, ignore_missing_keys=False ):
        self.base = base
        self.config = self.get_config()
        self.ignore_missing_keys = ignore_missing_keys

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
            if self.ignore_missing_keys == False:
                raise AnsibleError("Cannot find key %s " % key)
            else:
                return None

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
            if isinstance(scope_value, list):
                scope_value = ','.join([repr(i) for i in scope_value])
                display.vv(f"Jerakia scope converted list '{key}' to comma separated values")
            elif isinstance(scope_value, dict):
                scope_value = ','.join(scope_value.keys())
                display.vv(f"Jerakia scope converted dict '{key}' to comma separated values of keys")
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
        scope = self.scope(variables)
        kwargs = kwargs or {}
        options = {
            'namespace': namespace_str,
            'policy': policy,
        }

        params = scope.copy()
        params.update(options)
        params.update(kwargs)
        headers = self.headers()

        # Show debug URL
        arg_list = "?" + '&'.join([ f"{k}={v}" for k, v in params.items() ])
        header_list = ' '.join([ f"-H '{k}: {v}'" for k, v in headers.items() ])
        display.v(f"Jerakia query url: curl {header_list} '{endpoint_url}{arg_list}'")

        response = requests.get(endpoint_url, params=params, headers=headers)
        if response.status_code == requests.codes.ok:
            return json.loads(response.text)
        else:
            raise AnsibleError(f"Bad HTTP response, got: {response.text}")


# Entry point for Ansible starts here with the LookupModule class
class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):

        # Parse arguments
        kwargs = kwargs or {}
        enable_jinja = kwargs.pop('enable_jinja', True)
        jinja2_native = kwargs.pop('jinja2_native', False)
        ignore_missing_keys = kwargs.pop('ignore_missing_keys', False)

        # Instanciate Jerakia client
        jerakia = Jerakia(self, ignore_missing_keys=ignore_missing_keys)
        
        # Start jinja template engine
        if enable_jinja:
            if USE_JINJA2_NATIVE and not jinja2_native:
                templar = self._templar.copy_with_new_env(environment_class=AnsibleEnvironment)
            else:
                templar = self._templar

        # Look for each terms
        ret = []
        for term in terms:
            lookuppath = term.split('/')
            key = lookuppath.pop()
            namespace = lookuppath

            if not namespace:
                raise AnsibleError("No namespace given for lookup of key %s" % key)

            response = jerakia.lookup(key=key, namespace=namespace, variables=variables, kwargs=kwargs)

            # Render data with Jinja
            if enable_jinja:
                # Build a copy of environment vars
                vars = deepcopy(variables)

                # Render data with Templar
                with templar.set_temporary_context(available_variables=vars):
                    res = templar.template(response['payload'], preserve_trailing_newlines=True,
                                               convert_data=False, escape_backslashes=False)

                if USE_JINJA2_NATIVE and not jinja2_native:
                    # jinja2_native is true globally but off for the lookup, we need this text
                    # not to be processed by literal_eval anywhere in Ansible
                    res = NativeJinjaText(res)
            else:
                res = response['payload']

            # Append response to response array
            ret.append(res)

        return ret

