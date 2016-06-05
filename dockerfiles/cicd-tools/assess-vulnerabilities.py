#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""This script analyzes Clair generated vulnerabilities.
The script is intended to be incorporated into a CI process
to generate a non-zero exit status when vulnerabilities
exceed an acceptable threshold.
"""

import json
import optparse
import os
import sys


class Whitelist(object):

    def __init__(self, filename):
        object.__init__(self)

        self.filename = filename

        if self.filename:
            try:
                with open(self.filename) as fp:
                    self.whitelist = json.load(fp)
                    # :TODO: validate whitelist with jsonschema
            except Exception:
                msg = "Could not read whitelist from '%s'\n" % self.filename
                sys.stderr.write(msg)
                sys.exit(1)

    @property
    def ignoreSevertiesAtOrBelow(self):
        return self.whitelist('ignoreSevertiesAtOrBelow', 'Medium')


class Vulnerability(object):

    vulnerabilities_by_cve_id = {}

    vulnerabilities_by_severity = {}

    def __init__(self, vulnerability):
        object.__init__(self)

        self.vulnerability = vulnerability

        cls = type(self)

        if self.cve_id not in cls.vulnerabilities_by_cve_id:
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


class Layer(object):

    def __init__(self, filename):
        object.__init__(self)

        self.filename = filename

        self._vulnerabilities_loaded = False

    def __str__(self):
        return self.id

    def load_vulnerabilities(self):
        assert not self._vulnerabilities_loaded
        self._vulnerabilities_loaded = True

        try:
            with open(self.filename) as fp:
                features = json.load(fp).get('Layer', {}).get('Features', [])
                for feature in features:
                    vulnerabilities = feature.get('Vulnerabilities', [])
                    for vulnerability in vulnerabilities:
                        Vulnerability(vulnerability)
        except Exception:
            msg = "Could not read vulnerabilities from '%s'\n" % self.filename
            sys.stderr.write(msg)
            sys.exit(1)


class Layers(list):

    def __init__(self, directory):
        list.__init__(self)

        for filename in os.listdir(directory):
            self.append(Layer(os.path.join(directory, filename)))


class CommandLineParser(optparse.OptionParser):

    def __init__(self):

        optparse.OptionParser.__init__(
            self,
            'usage: %prog [options] <docker image>',
            description='cli to analyze results of Clair identified vulnerabilities')

        help = 'verbose - default = false'
        self.add_option(
            '--verbose',
            '-v',
            action='store_true',
            dest='verbose',
            help=help)

        default = None
        help = 'whitelist - default = %s' % default
        self.add_option(
            '--whitelist',
            '--wl',
            action='store',
            dest='whitelist',
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

    wl = Whitelist(clo.whitelist)

    for layer in Layers(cla[0]):
        layer.load_vulnerabilities()

    if clo.verbose:
        indent = '-' * 50

        print indent

        for severity in Vulnerability.vulnerabilities_by_severity.keys():
            print '%s - %d' % (
                severity,
                len(Vulnerability.vulnerabilities_by_severity[severity]),
            )

        for vulnerability in Vulnerability.vulnerabilities_by_cve_id.values():
            print indent
            print vulnerability.cve_id
            print json.dumps(vulnerability.vulnerability, indent=2)

        print indent

    sys.exit(0)
