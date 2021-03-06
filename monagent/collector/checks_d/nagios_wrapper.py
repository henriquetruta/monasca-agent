#!/bin/env python
"""Monasca Agent wrapper for Nagios checks.

"""

import hashlib
import json
import os
import pickle
import socket
import subprocess
import time

from monagent.collector.checks.services_checks import ServicesCheck, Status


class WrapNagios(ServicesCheck):

    """Inherit ServicesCheck class to process Nagios checks.

    """

    def __init__(self, name, init_config, agent_config, instances=None):
        ServicesCheck.__init__(self, name, init_config, agent_config, instances)

    @staticmethod
    def _do_skip_check(instance, last_run_data):
        """Determine whether or not to skip a check depending on
        the checks's check_interval, if specified, and the last
        time the check was run
        """
        if instance['name'] in last_run_data and 'check_interval' in instance:
            if time.time() < last_run_data[instance['name']] + instance['check_interval']:
                return True
        else:
            return False

    def _create_status_event(self, status, msg, instance):
        """Does nothing: status events are not yet supported by Mon API.

        """
        return

    def _check(self, instance):
        """Run the command specified by check_command and capture the result.

        """

        dimensions = {'observer_host': socket.getfqdn()}
        # Add per-instance dimensions, if any
        if 'dimensions' in instance.keys() and instance['dimensions'] is not None:
            dimensions.update(instance['dimensions'])

        if 'host_name' in instance:
            dimensions['target_host'] = instance['host_name']
        else:
            dimensions['target_host'] = socket.getfqdn()

        extra_path = self.init_config.get('check_path')

        last_run_path = self.init_config.get('temp_file_path')
        # Use a default last_run_file if no temp_file is specified in the YAML
        if last_run_path is None:
            last_run_path = '/dev/shm/'

        if last_run_path.endswith('/') is False:
            last_run_path += '/'
        last_run_file = (
            last_run_path +
            'nagios_wrapper_' +
            hashlib.md5(
                instance['name']).hexdigest() +
            '.pck')

        # Load last-run data from shared memory file
        last_run_data = {}
        if os.path.isfile(last_run_file):
            file_r = open(last_run_file, "r")
            last_run_data = pickle.load(file_r)
            file_r.close()

        # Exit here if it is not yet time to re-run this check
        if self._do_skip_check(instance, last_run_data) is True:
            return

        try:
            proc = subprocess.Popen(instance['check_command'].split(" "),
                                    env={"PATH": extra_path},
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            output = proc.communicate()
            # The check detail is all the text before the pipe
            detail = output[0].split('|')[0]
            # TODO(dschroeder): Save/send 'detail' when supported by the API
        except OSError:
            # Return an UNKNOWN code (3) if I have landed here
            self.gauge(instance['name'], 3, dimensions=dimensions)
            self.log.info(instance['check_command'].split(" ")[0] + " is missing or unreadable")
            return

        status_code = proc.poll()
        last_run_data[instance['name']] = time.time()
        self.gauge(instance['name'], status_code, dimensions=dimensions)
        # Return DOWN on critical, UP otherwise
        if status_code == "2":
            return Status.DOWN, "DOWN: {}".format(detail)
        return Status.UP, "UP: {}".format(detail)

        # Save last-run data
        file_w = open(last_run_file, "w")
        pickle.dump(last_run_data, file_w)
        file_w.close()
