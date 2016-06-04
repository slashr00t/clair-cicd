#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""This script summarizes the output of Clair's analyze-local-images
utility. The script is intended to be incorporated into a CI process
to generate a non-zero exit status when the vulnerability report
exceeds the accepted threshold.

docker \
    run \
    --rm \
    --link clair-52d5afeb97ad0757:clair \
    -v /tmp:/tmp \
    -v /var/run/docker.sock:/var/run/docker.sock \
    simonsdave/clair-cicd-tools \
    assess-image-risk.py --drapi http://172.17.42.1:2375 --clair http://clair:6060 simonsdave/ecs-services:latest
"""

import httplib
import json
import optparse
import os
import sys
import urllib

import requests


class Vulnerability(object):

    vulnerabilities = []

    vulnerabilities_by_cve_id = {}

    vulnerabilities_by_severity = {}

    def __init__(self, vulnerability):
        object.__init__(self)

        self.vulnerability = vulnerability

        cls = type(self)

        if self.cve_id in cls.vulnerabilities_by_cve_id:
            return

        cls.vulnerabilities.append(self)

        cls.vulnerabilities_by_cve_id[self.cve_id] = self

        if self.severity not in cls.vulnerabilities_by_severity:
            cls.vulnerabilities_by_severity[self.severity] = []
        cls.vulnerabilities_by_severity[self.severity].append(self)

    def __str__(self):
        return self.cve_id

    @property
    def cve_id(self):
        return self.vulnerability['Name']

    @property
    def severity(self):
        return self.vulnerability['Severity']


class CommandLineParser(optparse.OptionParser):

    def __init__(self):

        optparse.OptionParser.__init__(
            self,
            'usage: %prog [options] <docker image>',
            description='cli to analyze results of Clair identified vulnerabilities')

        default = 'http://172.17.42.1:2375'
        help = 'drapi - default = %s' % default
        self.add_option(
            '--drapi',
            action='store',
            dest='docker_remote_api_endpoint',
            default=default,
            type='string',
            help=help)

        default = 'http://clair:6060'
        help = 'clair - default = %s' % default
        self.add_option(
            '--clair',
            action='store',
            dest='clair_endpoint',
            default=default,
            type='string',
            help=help)

    def parse_args(self, *args, **kwargs):
        (clo, cla) = optparse.OptionParser.parse_args(self, *args, **kwargs)
        if len(cla) != 1:
            self.error('no docker image')

        return (clo, cla)


if __name__ == '__main__':

    clp = CommandLineParser()
    (clo, cla) = clp.parse_args()

    url = '%s/images/%s/history' % (
        clo.docker_remote_api_endpoint,
        urllib.quote_plus(cla[0]),
    )
    response = requests.get(url)
    if response.status_code != httplib.OK:
        msg = "Couldn't get image history for '%s' (%s)\n" % (
            cla[0],
            response.status_code,
        )
        sys.stderr.write(msg)
        sys.exit(1)

    layers = [layer['Id'] for layer in response.json()]

    for layer in layers:
        url = '%s/v1/layers/%s?vulnerabilities' % (
            clo.clair_endpoint,
            layer,
        )
        response = requests.get(url)
        if response.status_code != httplib.OK:
            msg = "Couldn't get vulnerabilities for layer '%s' (%s)\n" % (
                layer,
                response.status_code,
            )
            sys.stderr.write(msg)
            sys.exit(1)

        features = response.json().get('Layer', {}).get('Features', [])
        for feature in features:
            vulnerabilities = feature.get('Vulnerabilities', [])
            for vulnerability in vulnerabilities:
                Vulnerability(vulnerability)

    for severity in Vulnerability.vulnerabilities_by_severity.keys():
        print '%s - %d' % (
            severity,
            len(Vulnerability.vulnerabilities_by_severity[severity]),
        )

    for vulnerability in Vulnerability.vulnerabilities:
        print '-' * 50
        print vulnerability.cve_id
        print json.dumps(vulnerability.vulnerability, indent=2)

    sys.exit(0)
